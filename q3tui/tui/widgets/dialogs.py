"""The dialogs (spec/tui.md "Dialogs and notifications")."""

from __future__ import annotations

from textual import on
from textual.binding import Binding
from textual.widgets import Button, Static

from q3tui.engine.decisions import Question as EngineQuestion
from q3tui.tui.ui.alert_dialog import AlertDialog
from q3tui.tui.ui.dialog import (
    Dialog,
    DialogClose,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
)
from q3tui.tui.ui.input import Textarea
from q3tui.tui.ui.questionnaire import Question, QuestionChoice, Questionnaire
from q3tui.tui.ui.text_button import TextButton


def question_form(q: EngineQuestion) -> Question:
    choices = []
    for n, o in enumerate(q.options):
        value = o.get("id") or o.get("text") or str(n)
        text = o.get("text", value)
        impact = o.get("impact")
        default = " (default)" if q.default is not None and value == q.default else ""
        desc = ", ".join(f"{k}: {v}" for k, v in impact.items()) if isinstance(impact, dict) else (impact or "")
        choices.append(QuestionChoice(text + default, value, desc))
    if not q.options and q.default is not None:
        choices.append(QuestionChoice(f"{q.default} (default)", q.default))
    return Question(q.id, q.text, choices, description=f"{q.kind} · {q.key}", freeform=True)


class AnswerDialog(Dialog):
    """The Questionnaire of one question. Returns `{"answer": …, "hint": …}` or None."""

    def __init__(self, q: EngineQuestion) -> None:
        self.q = q
        super().__init__(DialogHeader(DialogTitle(f"Question {q.id}"), DialogDescription(f"asked by {q.step}")),
                         Questionnaire(question_form(q), keys="local", id="answer-form"), width=72)

    @on(Questionnaire.Submitted)
    def _submitted(self, event: Questionnaire.Submitted) -> None:
        event.stop()
        value = event.answers.get(self.q.id)
        if isinstance(value, dict):  # {choice, text} when a choice and a text are given
            value = value.get("value") or value.get("text")
        values = {o.get("id") or o.get("text") for o in self.q.options}
        if self.q.problem is not None and value not in values:  # a text alone: fix again with it as the hint
            self.dismiss({"answer": "fix_again", "hint": str(value)})
            return
        self.dismiss({"answer": str(value), "hint": None})


class ChangeDialog(Dialog):
    """A change request to a step (or to one item of it). Ctrl+S sends; returns the text or None."""

    BINDINGS = [Binding("ctrl+s", "send", "Send", show=False)]

    def __init__(self, step: str, item: str | None = None) -> None:
        title = f"Change {step}" + (f" · {item}" if item else "")
        super().__init__(DialogHeader(DialogTitle(title), DialogDescription("What should change? Ctrl+S sends.")),
                         Textarea("", rows=6, placeholder="Describe the change", id="change-text"),
                         DialogFooter(DialogClose("Cancel", None, key="escape"), TextButton("Send (Ctrl+S)", id="send")),
                         initial_focus="#change-text", width=72)

    def action_send(self) -> None:
        text = self.query_one("#change-text", Textarea).text.strip()
        self.dismiss(text or None)

    @on(Button.Pressed, "#send")
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_send()


class DefinitionDialog(Dialog):
    """The steps whose definition changed: [Run again] [Later]. Returns `rerun`, `later` or None."""

    def __init__(self, changes: list[dict]) -> None:
        lines = [f"{c['step']}  {c['old_version']} → {c['new_version']}  ({', '.join(c['files'][:4])}"
                 f"{'…' if len(c['files']) > 4 else ''})" for c in changes]
        super().__init__(DialogHeader(DialogTitle("The definition of some steps changed"),
                                      DialogDescription("Run them again as an update, or later.")),
                         Static("\n".join(lines), markup=False),
                         DialogFooter(DialogClose("Later", "later", key="escape"), DialogClose("Run again", "rerun")),
                         width=80)


def confirm(title: str, description: str = "", *, action: str = "Confirm") -> AlertDialog:
    return AlertDialog(title, description, action=action, cancel="Cancel", destructive=True)


def allow(what: str, content: str) -> AlertDialog:
    return AlertDialog(f"This project wants to run {what}", content, action="Allow", cancel="Deny")


def download(name: str, source: dict) -> AlertDialog:
    return AlertDialog(f"Download {name}?", f"{source.get('git')} at {source.get('ref')}", action="Download")


class ShortcutsDialog(Dialog):
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        text = "\n".join(f"{k:<24} {v}" for k, v in rows)
        super().__init__(DialogHeader(DialogTitle("Keyboard shortcuts")), Static(text, markup=False), width=72)


class CostDialog(Dialog):
    """The cost: total, session, assistant and each step that spent something; [Reset cost] and [Close].
    Returns `reset` or None."""

    def __init__(self, cost: dict, session: float) -> None:
        rows = [("Project (until reset)", cost["total_usd"] + cost.get("assistant_usd", 0.0)),
                ("This session", session), ("Assistant", cost.get("assistant_usd", 0.0))]
        rows += [(f"  {step}", usd) for step, usd in sorted(cost["steps"].items(), key=lambda kv: -kv[1]) if usd]
        width = max(len(name) for name, _ in rows) + 2
        table = "\n".join(f"{name:<{width}}${usd:>10,.4f}" for name, usd in rows)
        resets = cost.get("resets") or []
        note = f"Reset {len(resets)} time(s), last at {resets[-1]['at']}." if resets else "Never reset."
        super().__init__(DialogHeader(DialogTitle("Cost"), DialogDescription(note)), Static(table, markup=False),
                         DialogFooter(DialogClose("Close", None, key="escape"), DialogClose("Reset cost", "reset")),
                         width=64)
