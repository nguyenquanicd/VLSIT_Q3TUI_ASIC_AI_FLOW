"""Activities (the panel under Main) and the Log tab of a step: events as lines, each with its time
(spec/tui.md "Main", "Mouse")."""

from __future__ import annotations

from textual.content import Content
from textual.widgets import Static

from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.message_scroller import MessageScroller

MAX_LINES = 800
QUIET = {"sdk", "task_progress"}


def _short(value, limit: int = 300) -> str:
    one = " ".join(str(value).split())
    return one if len(one) <= limit else one[:limit - 1] + "…"


def describe(e: dict) -> Content | None:
    """One line for an event (a dict as in events.jsonl), or None for those not shown."""
    kind, step = e.get("kind"), e.get("step") or ""
    who = (f"{step} ", "bold") if step else ("", "")
    if kind in QUIET:
        return None
    if kind == "run_started":
        scope = e.get("scope") or {}
        what = " ".join(f"{k}={v}" for k, v in scope.items()) or "the flow"
        return Content.assemble((icon("gate_auto"), "$primary"), (f" run started: {what}", "bold"))
    if kind == "run_finished":
        outs = ", ".join(f"{s} {o}" for s, o in (e.get("outcomes") or {}).items())
        return Content.assemble((icon("done"), "$primary"), f" run finished: {outs}",
                                (f"  ${e.get('cost_usd') or 0:,.2f}", "dim"))
    if kind == "stage_started":
        return Content.assemble(("── ", "dim"), (e.get("stage", ""), "bold"), (" ──", "dim"))
    if kind == "stage_finished":
        reason = f" ({e['reason']})" if e.get("reason") else ""
        return Content.assemble(("── ", "dim"), f"{e.get('stage', '')} {e.get('outcome')}{reason}", (" ──", "dim"))
    if kind == "step_started":
        ch = e.get("changes") or {}
        what = "regenerate" if e.get("regenerate") else "first run" if ch.get("first_run") else "update"
        return Content.assemble((icon("step_running"), "$primary"), " ", who, (what, "dim"))
    if kind == "step_finished":
        result = e.get("result")
        glyph, style = {"done": ("step_done", "$text-success"), "failed": ("step_failed", "$text-error")}.get(
            result, ("step_blocked", "$text-warning"))
        tail = f": {_short(e['error'], 200)}" if e.get("error") else ""
        return Content.assemble((icon(glyph), style), " ", who, f"{result}{tail}",
                                (f"  ${e.get('cost_usd') or 0:,.2f}", "dim"))
    if kind == "step_skipped":
        reason = {"user": "your file is used", "up_to_date": "up to date"}.get(e.get("reason"), e.get("reason"))
        return Content.assemble((icon("selected"), "dim"), " ", who, (str(reason), "dim"))
    if kind == "task_started":
        return Content.assemble(("  ", ""), (icon("sparkle"), "$accent"), f" {e.get('task')}", (f"  {e.get('model')}", "dim"))
    if kind == "task_text":
        return Content.assemble(("    ", ""), (_short(e.get("text"), 400), "$text-muted"))
    if kind == "tool_call":
        return Content.assemble(("    ", ""), (icon("tool"), "dim"), f" {e.get('tool')} ", (_short(e.get("input"), 200), "dim"))
    if kind == "task_finished":
        err = e.get("error")
        return Content.assemble(("  ", ""), (icon("step_failed" if err else "done"), "$text-error" if err else "dim"),
                                f" {e.get('task')}", (f"  {err}" if err else "", "$text-error"),
                                (f"  ${e.get('cost_usd') or 0:,.2f} · {e.get('turns') or 0} turns", "dim"))
    if kind == "approval_waiting":
        return Content.assemble((icon("step_gate"), "$text-warning"), " ", who, "waiting for approval")
    if kind == "approval_resolved":
        return Content.assemble((icon("gate_human"), "$text-success"), " ", who,
                                f"{e.get('decision', '').replace('_', ' ')} by {e.get('by')}")
    if kind == "questions":
        return Content.assemble((icon("step_gate"), "$text-warning"), " ", who, f"{e.get('open')} open question(s)")
    if kind == "question_answered":
        return Content.assemble((icon("selected"), "dim"), " ", who, f"{e.get('id')} {e.get('status')} by {e.get('by')}")
    if kind == "loop_round":
        return Content.assemble(("↺ ", "$accent"), who,
                                f"fix round {e.get('round')}: {e.get('problems')} problem(s) → {', '.join(e.get('sent_to') or [])}")
    if kind == "loop_stopped":
        return Content.assemble(("↺ ", "$accent"), who, f"fix loop stopped: {e.get('reason')}")
    if kind == "definition_changed":
        names = ", ".join(s["step"] for s in e.get("steps") or [])
        return Content.assemble((icon("warning"), "$text-warning"), f" definition changed: {names}")
    if kind in ("log", "warning", "error"):
        style = {"warning": "$text-warning", "error": "$text-error"}.get(kind, "")
        glyph = {"warning": icon("warning"), "error": icon("error")}.get(kind, "·")
        return Content.assemble((glyph, style or "dim"), " ", who, (_short(e.get("message"), 600), style))
    return None


def line(e: dict) -> Static | None:
    body = describe(e)
    if body is None:
        return None
    ts = str(e.get("ts", ""))[11:19]
    return Static(Content.assemble((ts, "dim"), " ", body), classes="activity-line")


class Activities(MessageScroller):
    """The events of the run going on and the events outside runs of this session."""

    DEFAULT_CSS = """
    Activities .activity-line { height: auto; padding: 0 1; }
    """

    async def write(self, e: dict) -> None:
        item = line(e)
        if item is None:
            return
        await self.add(item)
        extra = len(self.viewport.children) - MAX_LINES
        for old in list(self.viewport.children)[:max(0, extra)]:
            await old.remove()
