"""One LLM query on the Codex CLI (`codex exec --json`): the counterpart of the Claude Agent SDK query in `llm/runtime.py`.

`runtime.run_stage` picks the backend (`llm.backend`); the retry, the cost accounting and the result type are shared. A query:

- starts the in-process tool endpoint (`bridge.ToolBridge`): the stage's Q3TUI tools plus the confined file tools (`files.py`);
- runs `codex exec --json` (sandbox read-only, no shell, approvals off) with the prompt on stdin, in the stage's folder;
- turns the JSONL events into the same Q3TUI events the Claude backend emits (`llm_text`, `tool_call`, `sdk`, …);
- a first turn with a result model passes the schema as `--output-schema`; a resumed turn asks for a JSON block instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from q3tui.core.config import Config
from q3tui.core.events import StepEmitter
from q3tui.llm import runtime
from q3tui.llm.codex.bridge import SERVER_NAME, TOKEN_ENV, ToolBridge
from q3tui.llm.codex.files import file_tools, usage_note

EFFORTS = {"max": "xhigh", "xhigh": "xhigh", "high": "high", "medium": "medium", "low": "low", "minimal": "minimal"}
LOST_SESSION_MARKERS = ("no saved session", "session not found", "no session found", "no rollout found")
STDOUT_LIMIT = 32 * 1024 * 1024  # one JSONL event (a long command output / file) per line


class CodexError(RuntimeError):
    """The Codex CLI failed (missing binary, crash, a failed turn); the message is shown to the user."""


@dataclass
class CodexOptions:
    model: str | None
    effort: str | None
    system_prompt: str
    cwd: Path
    tools: list[Any]
    schema: dict | None  # the result's JSON Schema (pydantic's, before the strict form)
    resume: str | None
    fork_session: bool = False  # (kept for runtime.py; Codex cannot fork a session)
    bin: str = "codex"
    sandbox: str = "read-only"
    shell: bool = False
    extra_args: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    tool_timeout_s: int = 7 * 24 * 3600
    prices: dict[str, dict[str, float]] = field(default_factory=dict)
    startup_timeout_s: int = 30
    json_block: bool = False  # the result comes as a JSON block in the reply (no --output-schema)


@dataclass
class CodexResult:
    """What `runtime._run_stage` reads of a query (the fields of the SDK's ResultMessage it uses)."""

    result: str
    session_id: str | None
    num_turns: int
    is_error: bool
    subtype: str
    errors: list[str]
    duration_ms: int
    total_cost_usd: float
    model_usage: dict[str, dict[str, float]]
    usage: dict[str, int]
    structured_output: Any = None
    json_block = True  # (class attribute) validation errors ask for a JSON block, not a StructuredOutput call


# -- schema --------------------------------------------------------------------------------------------------------


def strict_schema(node: Any) -> Any:
    """The schema in OpenAI's strict form: every property required, an optional one may be null."""
    if isinstance(node, list):
        return [strict_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: strict_schema(v) for k, v in node.items() if k != "properties"}
    if "properties" in node:
        required = set(node.get("required") or [])
        props = {}
        for name, sub in node["properties"].items():
            sub = strict_schema(sub)
            props[name] = sub if name in required else _nullable(sub)
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def _nullable(sub: dict) -> dict:
    if isinstance(sub.get("type"), str):
        sub = {**sub, "type": [sub["type"], "null"]}
        if "enum" in sub and None not in sub["enum"]:
            sub["enum"] = [*sub["enum"], None]
        return sub
    if "anyOf" in sub:
        return sub if any(b.get("type") == "null" for b in sub["anyOf"]) else {**sub, "anyOf": [*sub["anyOf"], {"type": "null"}]}
    return {"anyOf": [sub, {"type": "null"}]}


def prune_nulls(data: Any, schema: Any) -> Any:
    """The answer without the nulls of optional fields (they stand for 'not given': the model's defaults apply)."""
    if isinstance(data, dict) and isinstance(schema, dict):
        props, required = schema.get("properties") or {}, set(schema.get("required") or [])
        return {k: prune_nulls(v, props.get(k, {})) for k, v in data.items() if not (v is None and k in props and k not in required)}
    if isinstance(data, list) and isinstance(schema, dict):
        return [prune_nulls(v, schema.get("items", {})) for v in data]
    return data


# -- options / command -------------------------------------------------------------------------------------------


def _toml(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)  # (a JSON string / number / array / bool is a TOML value)


def build_options(stage: runtime.Stage, cfg: Config, emit: StepEmitter | None = None) -> CodexOptions:
    cx = cfg.llm.codex
    tools = [runtime.capped(t, cfg.llm.tool_output_limit) for t in [*stage.sdk_tools, *file_tools(stage)]]
    system_prompt = stage.system_prompt if stage.role else stage.system_prompt + runtime.access_note(stage)
    step = emit.step if emit is not None else None
    entry = getattr(cfg.llm.steps, step, None) if step else None
    effort = stage.effort or (getattr(entry, "effort", "default") if getattr(entry, "effort", "default") not in ("default", "none") else None) \
        or cx.effort
    schema = runtime.output_schema(stage.output_model) if stage.output_model and not stage.submit_tool else None
    return CodexOptions(
        model=cx.model, effort=EFFORTS.get(effort) if effort else None, system_prompt=system_prompt + usage_note(stage),
        cwd=stage.cwd, tools=tools, schema=schema, resume=stage.resume, bin=cx.bin, sandbox=cx.sandbox, shell=cx.shell,
        extra_args=list(cx.extra_args), config=dict(cx.config), prices=cx.prices, startup_timeout_s=cx.startup_timeout_s,
        env={**cfg.llm.env}, tool_timeout_s=int(cfg.llm.timeout_s or 7 * 24 * 3600), json_block=bool(stage.text_json))


def command(options: CodexOptions, bridge_url: str, schema_file: Path | None) -> list[str]:
    """The `codex exec` argument list (the prompt follows on stdin)."""
    c = {"approval_policy": "never", "sandbox_mode": options.sandbox, "project_doc_max_bytes": 0,
         f"mcp_servers.{SERVER_NAME}.url": bridge_url, f"mcp_servers.{SERVER_NAME}.bearer_token_env_var": TOKEN_ENV,
         f"mcp_servers.{SERVER_NAME}.tool_timeout_sec": options.tool_timeout_s,
         f"mcp_servers.{SERVER_NAME}.startup_timeout_sec": options.startup_timeout_s,
         "features.shell_tool": options.shell, **options.config}
    if options.effort:
        c["model_reasoning_effort"] = options.effort
    args = [options.bin, "exec", "--json", "--skip-git-repo-check"]
    if options.model:
        args += ["-m", options.model]
    if schema_file is not None:
        args += ["--output-schema", str(schema_file)]
    for key, value in c.items():
        args += ["-c", f"{key}={_toml(value)}"]
    args += options.extra_args
    if options.resume:
        args += ["resume", options.resume]
    return [*args, "-"]


def _cost(options: CodexOptions, model: str, tokens: dict[str, int]) -> float:
    price = options.prices.get(model) or options.prices.get("*")
    if not price:
        return 0.0
    fresh = max(0, tokens["input"] - tokens["cached"])
    return (fresh * price.get("input", 0) + tokens["cached"] * price.get("cached_input", price.get("input", 0))
            + tokens["output"] * price.get("output", 0)) / 1e6


# -- the query --------------------------------------------------------------------------------------------------


async def query_once(prompt: str, options: CodexOptions, stage: runtime.Stage, emit: StepEmitter
                     ) -> tuple[CodexResult | None, list[str], str | None]:
    binary = options.bin if Path(options.bin).is_file() else shutil.which(options.bin)
    if binary is None:
        raise CodexError(f"the Codex CLI `{options.bin}` was not found: install it (npm i -g @openai/codex) or set llm.codex.bin")
    first = options.resume is None
    text = f"{options.system_prompt}\n\n{prompt}" if first else prompt
    if options.schema and (options.json_block or not first):  # no --output-schema: the result as a JSON block
        text += runtime.TEXT_JSON.format(schema=json.dumps(options.schema, separators=(",", ":")))
    started = time.monotonic()
    texts: list[str] = []
    tokens = {"input": 0, "cached": 0, "output": 0, "thinking": 0}
    state: dict[str, Any] = {"session": options.resume, "turns": 0, "error": None, "last": ""}
    async with ToolBridge(options.tools, emit, stage.name) as bridge, _schema_file(options, first) as schema_file:
        args = command(options, bridge.url, schema_file)
        launch = [sys.executable, binary] if binary.endswith(".py") else [binary]  # (a script stands in for the CLI in tests)
        proc = await asyncio.create_subprocess_exec(
            *launch, *args[1:], cwd=str(options.cwd), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=STDOUT_LIMIT, env={**os.environ, **options.env, TOKEN_ENV: bridge.token})
        stderr_tail: list[str] = []

        async def drain_stderr() -> None:
            async for raw in proc.stderr:
                stderr_tail.append(raw.decode(errors="replace").rstrip())
                del stderr_tail[:-30]

        err_task = asyncio.create_task(drain_stderr())
        try:
            proc.stdin.write(text.encode())
            await proc.stdin.drain()
            proc.stdin.close()
            async for raw in proc.stdout:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue  # (a stray log line)
                _handle(event, stage, emit, texts, tokens, state)
            code = await proc.wait()
        finally:
            if proc.returncode is None:  # cancelled (stage timeout) or failed: no orphan agent
                proc.kill()
                await proc.wait()
            await err_task
    if state["error"] is None and state.get("soft_error") and state["turns"] == 0:
        state["error"] = state["soft_error"]
    if state["error"] is None and code != 0:
        state["error"] = (stderr_tail[-1] if stderr_tail else f"codex exited with code {code}")
    if state["error"] and options.resume and any(m in " ".join(stderr_tail + [state["error"]]).lower() for m in LOST_SESSION_MARKERS):
        raise CodexError(f"{runtime.LOST_SESSION}: {state['error']}")
    model = options.model or "codex"
    usage = {"input_tokens": tokens["input"], "cached_input_tokens": tokens["cached"], "output_tokens": tokens["output"],
             "reasoning_output_tokens": tokens["thinking"]}
    cost = _cost(options, model, tokens)
    model_usage = {model: {"inputTokens": max(0, tokens["input"] - tokens["cached"]), "cacheReadInputTokens": tokens["cached"],
                           "outputTokens": tokens["output"], "thinkingTokens": tokens["thinking"], "costUSD": cost}}
    final = state["last"]
    structured = None
    if options.schema and final:
        try:
            structured = prune_nulls(runtime._extract_json(final), options.schema)
        except ValueError:
            structured = None
    result = CodexResult(result=final, session_id=state["session"], num_turns=max(1, state["turns"]), is_error=bool(state["error"]),
                         subtype="error_during_execution" if state["error"] else "success", errors=[state["error"]] if state["error"] else [],
                         duration_ms=int((time.monotonic() - started) * 1000), total_cost_usd=cost, model_usage=model_usage,
                         usage=usage, structured_output=structured)
    emit("sdk", stage=stage.name, message={"type": "ResultMessage", "total_cost_usd": cost, "model_usage": model_usage, "usage": usage,
                                           "duration_ms": result.duration_ms, "num_turns": result.num_turns, "is_error": result.is_error})
    return result, texts, None


class _schema_file:
    """A temp file holding the strict result schema (first turn with a result model); None otherwise."""

    def __init__(self, options: CodexOptions, first: bool):
        self.use = bool(options.schema) and first and not options.json_block
        self.options, self.dir = options, None

    async def __aenter__(self) -> Path | None:
        if not self.use:
            return None
        self.dir = tempfile.TemporaryDirectory(prefix="q3tui-codex-")
        path = Path(self.dir.name) / "result.schema.json"
        path.write_text(json.dumps(strict_schema(self.options.schema)))
        return path

    async def __aexit__(self, *exc) -> None:
        if self.dir is not None:
            self.dir.cleanup()


def _handle(event: dict, stage: runtime.Stage, emit: StepEmitter, texts: list[str], tokens: dict, state: dict) -> None:
    kind = event.get("type", "")
    emit("sdk", stage=stage.name, message={"type": f"codex.{kind}", **{k: v for k, v in event.items() if k != "type"}})
    item = event.get("item") or {}
    if kind == "thread.started":
        state["session"] = event.get("thread_id") or state["session"]
    elif kind == "item.started" and item.get("type") in ("mcp_tool_call", "command_execution", "file_change"):
        name = f"mcp__{item.get('server')}__{item.get('tool')}" if item.get("type") == "mcp_tool_call" else item.get("type")
        emit("tool_call", stage=stage.name, tool=name, input=runtime._short(item.get("arguments") or item.get("command") or ""))
    elif kind == "item.completed":
        if item.get("type") == "agent_message" and (item.get("text") or "").strip():
            texts.append(item["text"])
            state["last"] = item["text"]
            emit("llm_text", stage=stage.name, text=item["text"].strip())
        elif item.get("type") == "error":
            emit("warning", message=f"{stage.name}: {item.get('message', '')}")
    elif kind == "turn.completed":
        state["turns"] += 1
        u = event.get("usage") or {}
        tokens["input"] += u.get("input_tokens", 0)
        tokens["cached"] += u.get("cached_input_tokens", 0)
        tokens["output"] += u.get("output_tokens", 0)
        tokens["thinking"] += u.get("reasoning_output_tokens", 0)
    elif kind == "turn.failed":
        state["error"] = (event.get("error") or {}).get("message") or "the turn failed"
    elif kind == "error":  # (also sent for a reconnect that then works: it only counts when no turn finished)
        state["soft_error"] = event.get("message") or "codex reported an error"
