"""The assistant: a chat that does what you ask with the same actions you have (spec/assistant.md)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from q3tui.engine import EngineError, Ops
from q3tui.flowdef import Flow
from q3tui.llm import runtime as llm
from q3tui.llm.runtime import FILE_TOOLS, Access

FIXED = """You are the assistant of Q3TUI, a tool that runs a chip design flow (stages of steps that write
artifacts, with gates, questions and a fix loop). You act through your tools, the same actions the user has.

Rules:
- Act instead of explaining how to. Use the tools; cite file names, step names and question ids.
- Approve only when the user asks you to.
- Never promise to do something later: you cannot act after your reply. When you must wait for a run, call
  `run` with `wait: true`.
- After acting, say briefly what changed and which steps are now stale.
- Reply in the language the user writes in.
- Each message starts with a [TUI context] line: the step, tab and item the user is looking at. "This" or "it"
  means that. What you may read and write follows that step, as the note at the start of the message says.
- To work on another step, ask the user to look at it.
"""


def flow_part(flow: Flow) -> str:
    """The flow, as Q3TUI built it from the flow files (never named in code)."""
    lines = [f"## The flow `{flow.name}` ({flow.version})", flow.description, ""]
    if flow.body.strip():
        lines += [flow.body.strip(), ""]
    for stage in flow.stages:
        lines.append(f"### Stage `{stage.name}`")
        for sid in stage.steps:
            inst = flow.instances[sid]
            lines.append(f"- Step `{sid}`: {inst.description}")
            if inst.inputs:
                lines.append("  Inputs: " + ", ".join(i.artifact + (f" (your file {i.path})" if i.path else "")
                                                    for i in inst.inputs))
            if inst.outputs:
                lines.append("  Outputs: " + ", ".join(f"`{o.artifact}` → `{o.path or 'in place'}`" for o in inst.outputs))
            if inst.questions:
                lines.append("  Asks: " + ", ".join(inst.questions))
    return "\n".join(lines)


class Host(Protocol):
    """The TUI side: it shows the cards that ask you, and says what you are looking at."""

    async def confirm(self, text: str) -> bool: ...

    async def ask_user(self, question: str, choices: list[str]) -> str | None: ...

    def context(self) -> dict: ...  # {step, tab, item}


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    fn: Callable[[dict], Awaitable[str]]


class Assistant:
    def __init__(self, ops: Ops, host: Host, emit: Callable[[str, dict], None]):
        self.ops, self.host, self.emit = ops, host, emit
        self.engine = ops.engine
        self.dir = self.engine.project.assistant_dir
        self.prompt = FIXED + "\n" + flow_part(self.engine.flow)
        self.task: asyncio.Task | None = None

    # -- session ------------------------------------------------------------------------------------

    @property
    def _file(self) -> Path:
        return self.dir / "session.json"

    def _session(self) -> dict:
        s = json.loads(self._file.read_text()) if self._file.is_file() else {}
        digest = hashlib.sha256(self.prompt.encode()).hexdigest()
        if s.get("flow") != digest:  # another flow (or another version of it): a new session
            s = {"flow": digest}
        return s

    def _save(self, s: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(s, indent=1))

    def new_chat(self) -> None:
        if self._file.is_file():
            self._file.unlink()

    def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()

    # -- what it may read and write -----------------------------------------------------------------

    def access(self, step: str | None) -> Access:
        root = self.engine.root
        state = self.engine.project.state
        if not step or step not in self.engine.flow.instances:
            return Access(root, [root], [], state)
        inst = self.engine.flow.instances[step]
        allowed = self.engine._readable(inst)
        write = [t for o in inst.outputs if (t := self.engine.artifacts.target(o.artifact)) is not None]
        write += [self.engine.root / i.path.split("*")[0] for i in inst.inputs if i.path]
        return Access(root, allowed["read"], write, state)

    # -- asking -------------------------------------------------------------------------------------

    async def ask(self, text: str) -> None:
        self.task = asyncio.current_task()
        ctx = self.host.context()
        access = self.access(ctx.get("step"))
        context = "[TUI context] " + (", ".join(f"{k}: {v}" for k, v in ctx.items() if v) or "the overview")
        message = f"{context}\n{access.note([])}\n\n{text}"
        s = self._session()
        options = self._options(access, s.get("id"))
        try:
            await self._query(message, options, s)
        except asyncio.CancelledError:
            self.emit("stopped", {})
            raise
        except Exception as exc:  # noqa: BLE001 -- shown in the chat
            if s.get("id") and llm.LOST_SESSION in str(exc).lower():
                s = {"flow": s.get("flow")}
                self.emit("warning", {"message": "the assistant's earlier session was not found; a new one is opened"})
                await self._query(message, self._options(access, None), s)
            else:
                self.emit("error", {"message": str(exc)})

    async def _query(self, message: str, options, s: dict) -> None:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

        async for m in llm.query(prompt=message, options=options):
            if isinstance(m, AssistantMessage):
                for block in m.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        self.emit("text", {"text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        self.emit("tool", {"tool": block.name, "input": block.input})
            elif isinstance(m, ResultMessage):
                total = m.total_cost_usd or 0.0
                cost = max(0.0, total - (s.get("cost") or 0.0))
                self.engine.state.assistant_cost_usd += cost
                self.engine.save()
                s.update({"id": m.session_id, "cost": total})
                self._save(s)
                self.emit("done", {"cost_usd": cost, "error": m.subtype if m.is_error else None})

    def _options(self, access: Access, resume: str | None):
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, create_sdk_mcp_server, tool

        cfg = self.engine.config.config
        sdk_tools = []
        for t in self.tools(access):
            async def handler(args: dict, t=t) -> dict:
                try:
                    out = await t.fn(args)
                except (EngineError, ValueError, KeyError) as exc:
                    return {"content": [{"type": "text", "text": f"refused: {exc}"}], "is_error": True}
                return {"content": [{"type": "text", "text": out}]}

            sdk_tools.append(tool(t.name, t.description, t.params)(handler))
        server = create_sdk_mcp_server(llm.Q3TUI_MCP, tools=sdk_tools)

        async def guard(hook_input, tool_use_id, context):
            why = access.check(hook_input.get("tool_name"), hook_input.get("tool_input") or {})
            if why is None:
                return {}
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": why}}

        builtin = ["Read", "Grep", "Write", "Edit"]
        return ClaudeAgentOptions(
            model=cfg.llm.model, fallback_model=cfg.llm.fallback_model, effort=cfg.llm.effort,
            system_prompt=self.prompt, tools=builtin,
            allowed_tools=[*builtin, *(f"mcp__{llm.Q3TUI_MCP}__{t.name}" for t in sdk_tools)],
            permission_mode="dontAsk", mcp_servers={llm.Q3TUI_MCP: server}, cwd=str(self.engine.root),
            env={"ENABLE_CLAUDEAI_MCP_SERVERS": "false", **cfg.llm.env}, setting_sources=[], resume=resume,
            hooks={"PreToolUse": [HookMatcher(matcher=FILE_TOOLS, hooks=[guard])]},
        )

    # -- tools --------------------------------------------------------------------------------------

    async def _confirm_other_step(self, step: str | None, what: str) -> None:
        looking = self.host.context().get("step")
        if step and step != looking and not await self.host.confirm(f"{what} `{step}`, which you are not looking at?"):
            raise EngineError("declined by the user")

    async def _confirm(self, text: str) -> None:
        if not await self.host.confirm(text):
            raise EngineError("declined by the user")

    def tools(self, access: Access) -> list[Tool]:
        ops, eng = self.ops, self.engine

        async def status(a):
            return "\n".join(f"{s.id} ({s.stage}): {s.display}" + (f" — {s.reason}" if s.reason else "")
                             for s in ops.statuses())

        async def questions(a):
            qs = [q for q in eng.decisions.questions if q.status == "open" or a.get("all")]
            return "\n".join(f"{q.id} [{q.status}] {q.step} {q.kind} {q.key}: {q.text} (default {q.default}; "
                             f"options: {', '.join(o.get('id') or o.get('text', '') for o in q.options) or '-'})"
                             for q in qs) or "No open question."

        async def cost(a):
            return json.dumps(ops.cost(), indent=1)

        async def run(a):
            scope = {k: a.get(k) for k in ("only", "to", "stage") if a.get(k)}
            if a.get("from"):
                scope["from_"] = a["from"]
            target = a.get("only") or a.get("from") or a.get("to")
            await self._confirm_other_step(target, "Run")
            if a.get("wait"):
                outcomes = await ops.run(**scope)
                return "\n".join(f"{o.stage}: {o.outcome} {o.reason}".strip() for o in outcomes)
            ops.start(**scope)
            return "The run started."

        async def stop(a):
            ops.stop()
            return "Stopped."

        async def rerun(a):
            await self._confirm_other_step(a["step"], "Run again")
            if a.get("wait"):
                outcomes = await ops.run(rerun=[a["step"]])
                return "\n".join(f"{o.stage}: {o.outcome} {o.reason}".strip() for o in outcomes)
            ops.start(rerun=[a["step"]])
            return f"{a['step']} runs again."

        async def reset(a):
            await self._confirm(f"Reset `{a['step']}`{' only' if a.get('only') else ' and the steps after it'}?")
            return "Reset: " + ", ".join(ops.reset(a["step"], only=bool(a.get("only"))))

        async def approve(a):
            await self._confirm_other_step(a["step"], "Approve")
            if a.get("force"):
                await self._confirm(f"Approve `{a['step']}` by force (past blocking questions or items not reviewed)?")
            ops.approve(a["step"], force=bool(a.get("force")))
            return f"{a['step']} approved."

        async def request_change(a):
            await self._confirm_other_step(a["step"], "Send a change request to")
            r = ops.request_change(a["step"], a["text"], a.get("unit") or None)
            return f"Change request {r.id} sent to {a['step']}; it is now stale."

        async def answer(a):
            q = ops.answer(a["id"], a["answer"], hint=a.get("hint") or None, kind=a.get("kind") or None)
            return f"{q.id} {q.status}" + (f"; the decision goes to {q.owner}" if q.owner else "")

        async def review_item(a):
            await self._confirm_other_step(a["step"], "Review an item of")
            ops.review(a["step"], a["artifact"], a["item"], confirm=not a.get("change"), text=a.get("text", ""))
            return "Confirmed." if not a.get("change") else "Change requested."

        async def get_settings(a):
            cfg = ops.config
            key = a.get("key") or ""
            data = cfg.config.model_dump(mode="json")
            node = data
            for part in [p for p in key.split(".") if p]:
                node = node.get(part) if isinstance(node, dict) else None
            return f"{key or '(all)'} = {json.dumps(node)} (from {cfg.source(key) if key else 'merged'})"

        async def set_settings(a):
            layer = a.get("layer") or "session"
            if layer != "session":
                await self._confirm(f"Write `{a['key']}` = {a['value']!r} to the {layer} config file?")
            value = a["value"]
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                pass
            ops.settings(a["key"], value, layer=layer)
            return f"{a['key']} set in the {layer} layer."

        async def set_gate_mode(a):
            mode = a["mode"]
            if mode in ("auto", "unattended"):
                await self._confirm(f"Set the gate mode{' of ' + a['step'] if a.get('step') else ''} to `{mode}`?")
            ops.gate_mode(mode, a.get("step") or None)
            return f"Gate mode set to {mode}."

        async def ask_user(a):
            reply = await self.host.ask_user(a["question"], list(a.get("choices") or []))
            return reply if reply is not None else "The user did not answer."

        async def reset_cost(a):
            await self._confirm("Reset the cost?")
            ops.reset_cost()
            return "Cost reset."

        async def glob(a):
            return access.glob(a.get("pattern") or "*", a.get("path") or None)

        tools = [
            Tool("glob", "Find files by a glob pattern, optionally under a folder (path); lists only what you may read",
                 {"pattern": str, "path": str}, glob),
            Tool("status", "The display state of every step", {}, status),
            Tool("questions", "The open questions (all: true for every question)", {"all": bool}, questions),
            Tool("cost", "The cost, per step and in total", {}, cost),
            Tool("run", "Run the flow, or a scope: only, from, to (with from), stage. wait: true waits until it ends.",
                 {"only": str, "from": str, "to": str, "stage": str, "wait": bool}, run),
            Tool("stop", "Stop the run", {}, stop),
            Tool("rerun", "Run a step again as an update", {"step": str, "wait": bool}, rerun),
            Tool("reset", "Reset a step (and the steps after it, unless only)", {"step": str, "only": bool}, reset),
            Tool("approve", "Approve a step (only when the user asks)", {"step": str, "force": bool}, approve),
            Tool("request_change", "Send a step a change request", {"step": str, "text": str, "unit": str},
                 request_change),
            Tool("answer", "Answer a question by its id; for a stopped fix loop: fix_again (hint), other_input "
                           "(kind, hint) or accept", {"id": str, "answer": str, "hint": str, "kind": str}, answer),
            Tool("review_item", "Confirm a review item, or ask for a change to it (change: true, text)",
                 {"step": str, "artifact": str, "item": str, "change": bool, "text": str}, review_item),
            Tool("get_settings", "A setting (dotted key) and the layer it comes from", {"key": str}, get_settings),
            Tool("set_settings", "Set a setting (JSON value); layer: session (default), project or user",
                 {"key": str, "value": str, "layer": str}, set_settings),
            Tool("set_gate_mode", "Set the gate mode (manual, auto, unattended), of one step or of the flow",
                 {"mode": str, "step": str}, set_gate_mode),
            Tool("ask_user", "Ask the user a question with choices", {"question": str, "choices": list}, ask_user),
            Tool("reset_cost", "Reset the cost", {}, reset_cost),
        ]
        for action in ops.actions():
            async def call(a, action=action):
                if action.confirm:
                    await self._confirm(f"Run `{action.name}`? {action.doc}")
                return ops.call_action(action.name, **{k: str(v) for k, v in a.items() if k in action.params})

            tools.append(Tool(action.name, action.doc, {p: str for p in action.params}, call))
        return tools


def run_tool(tools: list[Tool], name: str, args: dict) -> Awaitable[Any]:
    """Call one tool by name (the TUI's `/` commands and tests)."""
    return next(t for t in tools if t.name == name).fn(args)
