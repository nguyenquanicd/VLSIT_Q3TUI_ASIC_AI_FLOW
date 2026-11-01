"""Activities (the panel under Main) and the Log tab of a step: the events, each with its time (spec/tui.md "Main",
"Mouse"). A step that runs is one line (a TraceLine, its spinner while it runs) whose LLM work and tool calls fold
under it: open while it runs, closed when it is over; a stage is a Marker separator."""

from __future__ import annotations

from collections.abc import Iterable

from textual.content import Content
from textual.widget import Widget

from q3tui.tui.ui.collapsible import CollapsibleContent
from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.marker import Marker
from q3tui.tui.ui.message_scroller import MessageScroller
from q3tui.tui.ui.trace import TraceCollapsible, TraceLine

MAX_LINES = 800
QUIET = {"sdk", "task_progress"}
TONE = {"ok": "$text-success", "warn": "$text-warning", "error": "$text-error", "accent": "$primary",
        "dim": "dim"}


def _short(value, limit: int = 300) -> str:
    one = " ".join(str(value).split())
    return one if len(one) <= limit else one[:limit - 1] + "…"


def _cost(e: dict) -> str:
    return f"${e.get('cost_usd') or 0:,.2f}"


class EventLine(TraceLine):
    """A TraceLine with the event's time first and its icon in the colour of its tone."""

    DEFAULT_CSS = """
    EventLine { height: auto; color: $foreground; }
    EventLine.-detail { color: $text-muted; }
    EventLine.-tone-warn { color: $text-warning; }
    """

    def __init__(self, title: str, ts: str = "", *, icon_name=None, description: str = "", tone: str = "",
                 status=None, detail: bool = False) -> None:
        super().__init__(title, icon_name=icon_name, description=description, status=status,
                         classes="-detail" if detail else None)
        self.ts, self.tone = ts, tone
        if tone == "warn":
            self.add_class("-tone-warn")

    def refresh_label(self) -> None:
        parts: list = [(self.ts, "dim"), " "] if self.ts else []
        glyph = self.glyph()
        if glyph:
            parts += [(glyph, TONE.get(self.tone, "")), " "]
        parts.append(self.label)
        if self.description:
            parts += ["  ", (self.description, "dim")]
        section = self.section
        if section is not None:
            parts += [" ", (icon("chevron_down" if section.open else "chevron_right"), "dim")]
        self.update(Content.assemble(*parts))


class _Step:
    """The line of a step's run and what folds under it."""

    def __init__(self, line: EventLine, what: str) -> None:
        self.line, self.what = line, what
        self.children: list[Widget] = []
        self.box: TraceCollapsible | None = None
        self.turns = 0
        self.over = False


class EventLog(MessageScroller):
    """`EventLog(events)` shows past events, every step closed; `write(e)` adds a live one."""

    DEFAULT_CSS = """
    EventLog CollapsibleContent { padding: 0 0 0 2; }
    EventLog TraceLine, EventLog Marker { padding: 0; }
    """

    def __init__(self, events: Iterable[dict] = (), *, id: str | None = None) -> None:
        self._steps: dict[str, _Step] = {}
        tops: list = []
        for e in events:
            tops += self._take(e, live=False)[0]
        items = []
        for t in tops[-MAX_LINES:]:
            if isinstance(t, _Step):
                t.box = TraceCollapsible(t.line, *t.children, open=False)
                t.children = []
                items.append(t.box)
            else:
                items.append(t)
        super().__init__(*items, id=id)

    async def write(self, e: dict) -> None:
        tops, inside = self._take(e, live=True)
        for step, child in inside:
            if step.box is not None and step.box.is_mounted:
                await step.box.query_one(CollapsibleContent).mount(child)
                if self.following:
                    self.call_after_refresh(self.jump_to_end)
        if tops:
            await self.add(*tops)
            extra = len(self.viewport.children) - MAX_LINES
            for old in list(self.viewport.children)[:max(0, extra)]:
                await old.remove()

    # -- one event -> new lines, or lines under a step ----------------------------------------------

    def _take(self, e: dict, *, live: bool) -> tuple[list, list[tuple[_Step, Widget]]]:
        kind, sid = e.get("kind"), e.get("step") or ""
        ts = str(e.get("ts", ""))[11:19]
        if kind in QUIET:
            return [], []
        step = self._steps.get(sid) if sid else None

        def under(child: Widget) -> tuple[list, list]:
            """A line of a step's run: under its line, else a line of its own."""
            if step is None:
                return [child], []
            if step.box is None:
                step.children.append(child)
                return [], []
            return [], [(step, child)]

        if kind == "run_started":
            scope = e.get("scope") or {}
            what = " ".join(f"{k}={v}" for k, v in scope.items()) or "the flow"
            return [EventLine(f"run started: {what}", ts, icon_name="gate_auto", tone="accent")], []
        if kind == "run_finished":
            outs = ", ".join(f"{s} {o}" for s, o in (e.get("outcomes") or {}).items())
            return [EventLine(f"run finished: {outs}", ts, icon_name="done", tone="accent", description=_cost(e))], []
        if kind == "stage_started":
            return [Marker(e.get("stage", ""), variant="separator")], []
        if kind == "stage_finished":
            reason = f" ({e['reason']})" if e.get("reason") else ""
            return [Marker(f"{e.get('stage', '')}: {e.get('outcome')}{reason}", variant="separator")], []
        if kind == "step_started":
            ch = e.get("changes") or {}
            what = "regenerate" if e.get("regenerate") else "first run" if ch.get("first_run") else "update"
            line = EventLine(sid, ts, description=what, status="running")
            step = self._steps[sid] = _Step(line, what)
            if not live:
                return [step], []
            step.box = TraceCollapsible(line, open=True)
            return [step.box], []
        if kind == "step_finished":
            result = e.get("result")
            glyph, tone = {"done": ("step_done", "ok"), "failed": ("step_failed", "error")}.get(
                result, ("step_blocked", "warn"))
            tail = f": {_short(e['error'], 200)}" if e.get("error") else ""
            turns = f" · {step.turns} turns" if step and step.turns else ""
            desc = f"{step.what if step else ''} · {result}{tail} · {_cost(e)}{turns}".lstrip(" ·")
            if step is None:
                return [EventLine(sid, ts, icon_name=glyph, tone=tone, description=desc)], []
            step.over = True
            line = step.line
            line.icon_name, line.tone, line.description = glyph, tone, desc
            line.set_status("error" if result == "failed" else None)
            if step.box is not None and step.box.is_mounted:
                step.box.set_open(False)
            return [], []
        if kind == "task_started":
            return under(EventLine(str(e.get("task")), ts, icon_name="sparkle", tone="accent",
                                   description=str(e.get("model") or ""), detail=True))
        if kind == "task_text":
            return under(EventLine(_short(e.get("text"), 400), ts, detail=True))
        if kind == "tool_call":
            return under(EventLine(str(e.get("tool")), ts, icon_name="tool", tone="dim",
                                   description=_short(e.get("input"), 200), detail=True))
        if kind == "task_finished":
            err = e.get("error")
            if step is not None:
                step.turns += e.get("turns") or 0
            return under(EventLine(str(e.get("task")), ts, icon_name="step_failed" if err else "done",
                                   tone="error" if err else "dim", detail=True,
                                   description=f"{err}" if err else f"{_cost(e)} · {e.get('turns') or 0} turns"))
        if kind in ("log", "warning", "error"):
            tone = {"warning": "warn", "error": "error"}.get(kind, "dim")
            glyph = {"warning": "warning", "error": "error"}.get(kind)
            title = f"{sid} {_short(e.get('message'), 600)}" if sid and (step is None or step.over) \
                else _short(e.get("message"), 600)
            line = EventLine(title, ts, icon_name=glyph, tone=tone, detail=kind == "log",
                             status="error" if kind == "error" else None)
            if step is not None and not step.over:  # while the step runs: under it
                return under(line)
            return [line], []
        if kind == "step_skipped":
            reason = {"user": "your file is used", "up_to_date": "up to date"}.get(e.get("reason"), e.get("reason"))
            return [EventLine(sid, ts, icon_name="selected", tone="dim", description=str(reason))], []
        if kind == "approval_waiting":
            return [EventLine(f"{sid} waiting for approval", ts, icon_name="step_gate", tone="warn")], []
        if kind == "approval_resolved":
            return [EventLine(f"{sid} {e.get('decision', '').replace('_', ' ')} by {e.get('by')}", ts,
                              icon_name="gate_human", tone="ok")], []
        if kind == "questions":
            return [EventLine(f"{sid} {e.get('open')} open question(s)", ts, icon_name="step_gate", tone="warn")], []
        if kind == "question_answered":
            return [EventLine(f"{sid} {e.get('id')} {e.get('status')} by {e.get('by')}", ts, icon_name="selected",
                              tone="dim")], []
        if kind == "loop_round":
            sent = ", ".join(e.get("sent_to") or [])
            return [EventLine(f"↺ {sid} fix round {e.get('round')}: {e.get('problems')} problem(s) → {sent}", ts,
                              tone="accent")], []
        if kind == "loop_stopped":
            return [EventLine(f"↺ {sid} fix loop stopped: {e.get('reason')}", ts, tone="accent")], []
        if kind == "definition_changed":
            names = ", ".join(s["step"] for s in e.get("steps") or [])
            return [EventLine(f"definition changed: {names}", ts, icon_name="warning", tone="warn")], []
        return [], []


class Activities(EventLog):
    """The events of the run going on and the events outside runs of this session."""
