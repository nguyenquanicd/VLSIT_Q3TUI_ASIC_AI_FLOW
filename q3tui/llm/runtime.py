"""How an LLM task runs (spec/llm-runtime.md): one session per step with its stage's system prompt, the step's
tools, what it may read and write, structured results, budgets, checkpoints and resume."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

from q3tui.config import ConfigLayers
from q3tui.engine.ctx import Ctx, StepError
from q3tui.flowdef import text as T
from q3tui.workspace.project import Project

if TYPE_CHECKING:  # the SDK takes a while to import: only to run a task
    from claude_agent_sdk import ClaudeAgentOptions

Q3TUI_MCP = "q3tui"
FILE_TOOLS = "Read|Grep|Glob|Write|Edit"
WRITE_TOOLS = {"Write", "Edit"}
OUTPUT_RETRIES = 2
LOST_SESSION = "no conversation found"
MAX_KEY_FILES = 5000

TEXT_JSON = """

Reply with the result as ONE JSON object in a ```json fenced block, nothing after it. Inside JSON strings write a
newline as \\n and a double quote as \\". Its schema:
```json
{schema}
```"""


def query(*, prompt: str, options: ClaudeAgentOptions):
    """claude_agent_sdk.query, imported on first use (tests replace this function with a fake LLM)."""
    from claude_agent_sdk import query as sdk_query

    return sdk_query(prompt=prompt, options=options)


class TaskError(StepError):
    """An LLM task without a valid result (or past its time or cost limit): `ctx.task` raises it."""


# -- what a task may read and write ----------------------------------------------------------------


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == r or path.is_relative_to(r) for r in roots)


class Access:
    """The lists a task's file tools are checked against (spec/flow.md "What the LLM may read")."""

    def __init__(self, root: Path, read: list[Path], write: list[Path], state: Path):
        self.root = root.resolve()
        self.write = sorted({p.resolve() for p in write})
        self.read = sorted({p.resolve() for p in read} | set(self.write))
        self.state = state.resolve()

    def _abs(self, raw: str) -> Path:
        p = Path(raw).expanduser()
        return (p if p.is_absolute() else self.root / p).resolve()

    def _rel(self, p: Path) -> str:
        return str(p.relative_to(self.root)) if p.is_relative_to(self.root) else str(p)

    def check(self, tool: str, args: dict) -> str | None:
        """Why the call is refused (None: allowed), in words the LLM can act on."""
        if tool == "Grep" and not args.get("path"):
            return ("give Grep a `path`: one of the files or folders this task may read: "
                    + ", ".join(self._rel(p) for p in self.read[:30]))
        for key in ("file_path", "path"):
            raw = args.get(key)
            if not isinstance(raw, str):
                continue
            p = self._abs(raw)
            if _inside(p, [self.state]):
                return f"`{raw}` is Q3TUI's own state; no task reads or writes it"
            if tool in WRITE_TOOLS:
                if not _inside(p, self.write):
                    allowed = ", ".join(self._rel(w) for w in self.write) or "nothing"
                    return f"`{self._rel(p)}` is not an output this step may write (it may write: {allowed})"
            elif not _inside(p, self.read) and not any(r.is_relative_to(p) for r in self.read):
                return f"`{self._rel(p)}` is not an input of this step"
        return None

    def glob(self, pattern: str, path: str | None = None, limit: int = 300) -> str:
        """The files a pattern matches that the task may read."""
        base = self._abs(path) if path else self.root
        if pattern.startswith(("/", "~")) or ".." in Path(pattern).parts:
            return "use a pattern relative to the path, for example **/*.md"
        found = []
        for p in sorted(base.glob(pattern)):
            rp = p.resolve()
            if not p.is_file() or _inside(rp, [self.state]) or not _inside(rp, self.read):
                continue
            found.append(self._rel(rp))
            if len(found) >= limit:
                found.append(f"… (the first {limit}; narrow the pattern)")
                break
        return "\n".join(found) or "No files found"

    def note(self, skills: list[Path]) -> str:
        read = ", ".join(self._rel(p) for p in self.read if p not in self.write) or "nothing"
        write = ", ".join(self._rel(p) for p in self.write) or "nothing"
        lines = [f"[Q3TUI] This task may read: {read}.", f"It may write: {write}."]
        if skills:
            lines.append("Skills (read the SKILL.md when it applies): "
                         + ", ".join(self._rel(s / "SKILL.md") for s in skills) + ".")
        return " ".join(lines)

    def files_for_key(self) -> list[tuple[str, int, float]]:
        out = []
        for p in self.read:
            files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else []
            for f in files:
                st = f.stat()
                out.append((str(f), st.st_size, st.st_mtime))
                if len(out) >= MAX_KEY_FILES:
                    return out
        return out


# -- sessions ---------------------------------------------------------------------------------------


class Sessions:
    """`.q3tui/state/sessions/<step>/session.json`: the session's id, its running totals, the message the step
    started at, and the last message."""

    def __init__(self, project: Project):
        self.project = project

    def file(self, step: str) -> Path:
        return self.project.session_dir(step) / "session.json"

    def get(self, step: str) -> dict:
        f = self.file(step)
        return json.loads(f.read_text()) if f.is_file() else {}

    def put(self, step: str, data: dict) -> None:
        f = self.file(step)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=1))

    def clear(self, step: str) -> None:
        shutil.rmtree(self.project.session_dir(step), ignore_errors=True)


def change_note(changes) -> str:
    """What changed since the step last ran, for the first task of an update (spec/llm-runtime.md)."""
    lines = ["[Q3TUI] What changed since the last run:"]
    for r in changes.requests:
        unit = f", unit {r['unit']}" if r.get("unit") else ""
        lines.append(f"- request ({r['source']}{unit}): {r['text']}")
    for c in changes.inputs:
        lines.append(f"- input {c['change']}: {c['artifact']}")
    for c in changes.params:
        lines.append(f"- param changed: {c['name']} {c['old']} → {c['new']}")
    if changes.definition_changed:
        lines.append(f"- the step's definition changed: {', '.join(changes.definition_changed)}")
    for a in changes.edited_outputs:
        lines.append(f"- you edited: {a}")
    return "\n".join(lines)


def _delta(result, base: dict | None) -> float:
    """The cost of this query alone: a resumed session reports the totals of the whole session."""
    cost = result.total_cost_usd or 0.0
    return max(0.0, cost - (base or {}).get("cost", 0.0))


def _input_tokens(result) -> int:
    u = result.usage or {}
    return int(u.get("input_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0) \
        + int(u.get("cache_creation_input_tokens", 0) or 0)


def _extract_json(text: str):
    fence = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text[text.find("{"):text.rfind("}") + 1]
    return json.loads(candidate, strict=False)


def _short(value, limit: int = 160) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {"type": type(obj).__name__, **{f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


class LLMRuntime:
    def __init__(self, project: Project, config: ConfigLayers, *,
                 approved: Callable[[str], bool] | None = None):
        self.project, self.config = project, config
        self.sessions = Sessions(project)
        self.approved = approved  # for an `mcp_servers.<name>.command` of the project
        self.change_notes: dict[str, str] = {}  # step -> the note for the first task of this run

    # -- the step's lifecycle (called by the engine) ------------------------------------------------

    def step_started(self, ctx: Ctx) -> None:
        sid = ctx._instance.id
        self.change_notes.pop(sid, None)
        if not ctx._regenerate and ctx.changes.any:
            self.change_notes[sid] = change_note(ctx.changes)
        if ctx._regenerate:  # a first run, a reset or a regenerate: a new session
            self.sessions.clear(sid)
            return
        s = self.sessions.get(sid)
        if s:
            s["start_uuid"] = s.get("last_uuid")
            self.sessions.put(sid, s)

    def step_finished(self, ctx: Ctx, result: str) -> None:
        sid = ctx._instance.id
        if result == "cancelled":  # the session forgets the cancelled work: it goes on from where the step started
            s = self.sessions.get(sid)
            if s:
                s["rewind_to"] = s.get("start_uuid")
                self.sessions.put(sid, s)
            return
        shutil.rmtree(self.project.cache_dir(sid), ignore_errors=True)

    # -- one task -----------------------------------------------------------------------------------

    def _settings(self, sid: str) -> tuple[str, str | None]:
        cfg = self.config.config
        own = cfg.steps.get(sid)
        return (own.model if own and own.model else cfg.llm.model), (own.effort if own and own.effort else cfg.llm.effort)

    async def task(self, ctx: Ctx, name: str, unit: str | None, vars: dict) -> Any:
        inst = ctx._instance
        sid = inst.id
        task = next(t for t in inst.tasks if t.name == name)
        values = dict(inst.params)
        if unit is not None and inst.units:
            values[inst.units["name"]] = unit
        values |= vars
        try:
            prompt = T.fill(task.prompt, values, where=f"task {name}")
            system = T.fill(ctx._stage.system_prompt or "", ctx._stage.params, where="SYSTEM PROMPT")
        except KeyError as exc:
            raise TaskError(str(exc.args[0])) from exc
        allowed = ctx._allowed
        access = Access(self.project.root, allowed["read"], allowed["write"], self.project.state)
        skills = [p for s in inst.skills if (p := ctx._lookup.folder("skills", s)) is not None]
        message = access.note(skills) + "\n\n" + prompt
        note = self.change_notes.pop(sid, None)
        if note:
            message = note + "\n\n" + message
        schema = json.loads((inst.folder / task.output).read_text()) if task.output.endswith(".json") else None
        model, effort = self._settings(sid)
        label = f"{name}[{unit}]" if unit is not None else name
        key = hashlib.sha256(json.dumps([name, unit, message, model, effort, schema, access.files_for_key()],
                                        default=str).encode()).hexdigest()
        cached = self.project.cache_dir(sid) / f"{key}.json"
        if cached.is_file():
            ctx.log(f"task {label}: the result kept from the interrupted run is used (no LLM call)")
            return json.loads(cached.read_text())["result"]
        timeout = self.config.config.llm.timeout_s
        try:
            if timeout:
                async with asyncio.timeout(timeout):
                    result, wrote = await self._run(ctx, label, message, system, schema, access, model, effort)
            else:
                result, wrote = await self._run(ctx, label, message, system, schema, access, model, effort)
        except TimeoutError as exc:
            ctx._emit_event("task_finished", task=label, cost_usd=0.0, turns=0, error="timeout")
            raise TaskError(f"task {label}: did not finish within {timeout} s (llm.timeout_s)") from exc
        if not wrote:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps({"task": label, "result": result}))
        return result

    async def _run(self, ctx, label, message, system, schema, access, model, effort):
        sid = ctx._instance.id
        session = self.sessions.get(sid)
        options = self._options(ctx, system, schema, access, model, effort, session)
        ctx._emit_event("task_started", task=label, model=model)
        prompt, text_json, retries, total, turns, wrote = message, False, 0, 0.0, 0, False
        while True:
            try:
                res, texts, w = await self._query(ctx, label, prompt, options)
            except Exception as exc:
                if options.resume and LOST_SESSION in str(exc).lower():
                    ctx.warn(f"task {label}: the step's session was not found; a new one is opened")
                    self.sessions.clear(sid)
                    session = {}
                    options = dataclasses.replace(options, resume=None, resume_session_at=None, fork_session=False)
                    continue
                ctx._emit_event("task_finished", task=label, cost_usd=round(total, 4), turns=turns, error=str(exc))
                raise TaskError(f"task {label}: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}") from exc
            wrote = wrote or w
            if res is None:
                raise TaskError(f"task {label}: the LLM ended without a result")
            cost = _delta(res, session.get("totals"))
            total += cost
            turns += res.num_turns or 0
            ctx._add_cost(cost)
            session = {**session, "id": res.session_id, "totals": {"cost": res.total_cost_usd or 0.0},
                       "last_uuid": getattr(res, "uuid", None) or session.get("last_uuid")}
            session.pop("rewind_to", None)
            self.sessions.put(sid, session)
            budget = self.config.config.llm.task_token_budget
            if budget and _input_tokens(res) > budget:
                ctx.warn(f"task {label}: read {_input_tokens(res):,} input tokens (llm.task_token_budget {budget:,})")
            if res.is_error:
                ctx._emit_event("task_finished", task=label, cost_usd=round(total, 4), turns=turns, error=res.subtype)
                raise TaskError(f"task {label}: {res.subtype}: {res.result or res.errors or ''}".strip())
            options = dataclasses.replace(options, resume=res.session_id, resume_session_at=None, fork_session=False)
            if schema is None:
                ctx._emit_event("task_finished", task=label, cost_usd=round(total, 4), turns=turns, error=None)
                return (res.result or "\n".join(texts)), wrote
            data = res.structured_output
            if data is None:
                try:
                    data = _extract_json(res.result or "\n".join(texts))
                except (ValueError, json.JSONDecodeError):
                    if text_json:
                        ctx._emit_event("task_finished", task=label, cost_usd=round(total, 4), turns=turns,
                                        error="no JSON result")
                        raise TaskError(f"task {label}: no JSON result") from None
                    text_json = True
                    ctx.warn(f"task {label}: no structured result; asking for it as a JSON block")
                    options = dataclasses.replace(options, output_format=None)
                    prompt = "Give your result." + TEXT_JSON.format(schema=json.dumps(schema, separators=(",", ":")))
                    continue
            errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
            if not errors:
                ctx._emit_event("task_finished", task=label, cost_usd=round(total, 4), turns=turns, error=None)
                return data, wrote
            problems = "; ".join(f"{'.'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors[:20])
            if retries >= OUTPUT_RETRIES:
                ctx._emit_event("task_finished", task=label, cost_usd=round(total, 4), turns=turns, error=problems)
                raise TaskError(f"task {label}: the result does not match its schema: {problems}")
            retries += 1
            ctx.warn(f"task {label}: the result does not match its schema; asked again ({retries}/{OUTPUT_RETRIES})")
            how = "a ```json block" if text_json else "the structured output"
            prompt = f"The result does not match its schema ({problems}). Give the complete, corrected result in {how}."

    async def _query(self, ctx, label: str, prompt: str, options):
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolUseBlock,
        )

        result, texts, wrote, last_progress = None, [], False, 0.0
        async for m in query(prompt=prompt, options=options):
            if isinstance(m, SystemMessage) and m.subtype == "compact_boundary":
                ctx.log(f"task {label}: the session's context was compacted")
            if isinstance(m, SystemMessage) and m.subtype == "thinking_tokens":
                now = time.monotonic()
                if now - last_progress >= 1.0:
                    last_progress = now
                    ctx._emit_event("task_progress", task=label, thinking_tokens=(m.data or {}).get("estimated_tokens"))
                continue
            ctx._emit_event("sdk", message=_jsonable(m))
            if isinstance(m, AssistantMessage):
                for block in m.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        texts.append(block.text)
                        ctx._emit_event("task_text", task=label, text=block.text.strip())
                    elif isinstance(block, ToolUseBlock) and block.name != "StructuredOutput":
                        wrote = wrote or block.name in WRITE_TOOLS
                        ctx._emit_event("tool_call", task=label, tool=block.name, input=_short(block.input))
            elif isinstance(m, ResultMessage):
                result = m
        return result, texts, wrote

    # -- options --------------------------------------------------------------------------------------

    def _options(self, ctx: Ctx, system: str, schema, access: Access, model: str, effort, session: dict):
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, create_sdk_mcp_server

        inst = ctx._instance
        cfg = self.config.config
        llm_tools = list(inst.llm_tools)
        builtin = [t for t in llm_tools if t != "Glob"]
        tools = self._mcp_tools(ctx, access, "Glob" in llm_tools)
        limit = cfg.llm.tool_output_limit
        tools = [_capped(t, limit) for t in tools]
        servers: dict[str, Any] = {}
        allowed = list(builtin)
        if tools:
            servers[Q3TUI_MCP] = create_sdk_mcp_server(Q3TUI_MCP, tools=tools)
            allowed += [f"mcp__{Q3TUI_MCP}__{t.name}" for t in tools]
        for name, s in cfg.mcp_servers.items():
            if s.type == "stdio":
                if self.config.source(f"mcp_servers.{name}.command") == "project" and self.approved is not None \
                        and not self.approved(s.command or ""):
                    ctx.warn(f"MCP server {name}: command not approved; not given to the LLM")
                    continue
                servers[name] = {"type": "stdio", "command": s.command, "args": s.args, "env": s.env}
            else:
                servers[name] = {"type": s.type, "url": s.url, "headers": s.headers}
            allowed.append(f"mcp__{name}")
        thinking = None
        if effort is None and cfg.llm.thinking_budget is not None:
            b = cfg.llm.thinking_budget
            thinking = {"type": "disabled"} if b == 0 else {"type": "enabled", "budget_tokens": max(1024, b)}

        async def guard(hook_input, tool_use_id, context):
            why = access.check(hook_input.get("tool_name"), hook_input.get("tool_input") or {})
            if why is None:
                return {}
            ctx.warn(f"refused {hook_input.get('tool_name')}: {why}")
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": why}}

        rewind = session.get("rewind_to")
        return ClaudeAgentOptions(
            model=model, fallback_model=cfg.llm.fallback_model, effort=effort, thinking=thinking,
            system_prompt=system, tools=builtin, allowed_tools=allowed, permission_mode="dontAsk",
            mcp_servers=servers, cwd=str(self.project.root), max_turns=None, max_budget_usd=cfg.llm.task_max_cost,
            output_format={"type": "json_schema", "schema": schema} if schema else None,
            env={"MCP_TOOL_TIMEOUT": str((cfg.llm.timeout_s or 7 * 24 * 3600) * 1000),
                 "ENABLE_CLAUDEAI_MCP_SERVERS": "false", **cfg.llm.env},
            setting_sources=[], resume=session.get("id"),
            fork_session=bool(rewind and session.get("id")), resume_session_at=rewind if session.get("id") else None,
            hooks={"PreToolUse": [HookMatcher(matcher=FILE_TOOLS, hooks=[guard])]},
        )

    def _mcp_tools(self, ctx: Ctx, access: Access, glob: bool) -> list:
        from claude_agent_sdk import tool

        inst = ctx._instance
        out = []
        if glob:
            @tool("glob", "Find files by a glob pattern (for example \"**/*.md\"), optionally under a folder (`path`). "
                          "Lists only the files this task may read.", {"pattern": str, "path": str})
            async def glob_tool(args: dict) -> dict:
                text = access.glob(args.get("pattern") or "*", args.get("path") or None)
                return {"content": [{"type": "text", "text": text}]}

            out.append(glob_tool)
        if "tools_available" in inst.mcp_tools:
            @tool("tools_available", "Which tool roles of this step can run now", {})
            async def tools_available(args: dict) -> dict:
                lines = []
                for t in inst.tools:
                    why = ctx._tool_available(t["role"])
                    lines.append(f"- {t['role']}: {'available' if why is None else 'NOT available: ' + why}")
                return {"content": [{"type": "text", "text": "\n".join(lines) or "This step uses no tool."}]}

            out.append(tools_available)
        own = ctx._code.mcp_tools() if hasattr(ctx._code, "mcp_tools") else {}
        for name in inst.mcp_tools:
            if name == "tools_available":
                continue
            if name not in own:
                raise StepError(f"mcp tool `{name}` is neither built in nor a `@mcp_tool` of step.py")
            out.append(self._step_tool(ctx, own[name]))
        return out

    @staticmethod
    def _step_tool(ctx: Ctx, spec: dict):
        from claude_agent_sdk import tool

        method = spec["method"]

        @tool(spec["name"], spec["description"], spec["params"])
        async def run(args: dict) -> dict:
            try:
                out = method(ctx, args)
                if asyncio.iscoroutine(out):
                    out = await out
            except Exception as exc:  # noqa: BLE001 -- the LLM gets the error and can act on it
                return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
            if isinstance(out, dict) and "content" in out:
                return out
            text = out if isinstance(out, str) else json.dumps(out, default=str)
            return {"content": [{"type": "text", "text": text}]}

        return run


def _capped(t, limit: int):
    """The same tool with its text cut to `limit` characters (head and tail kept)."""
    handler = t.handler

    async def wrapped(args: dict) -> dict:
        out = await handler(args)
        items = []
        for c in out.get("content", []):
            text = c.get("text") if isinstance(c, dict) else None
            if text is not None and len(text) > limit:
                head, tail = text[:limit * 2 // 3], text[-limit // 3:]
                c = {**c, "text": f"{head}\n… [{len(text) - len(head) - len(tail)} characters cut by Q3TUI] …\n{tail}"}
            items.append(c)
        return {**out, "content": items}

    return dataclasses.replace(t, handler=wrapped)
