"""Questionnaire, following shadcn's Questionnaire: a few questions asked one at a time."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input as TextualInput
from textual.widgets import Static

from q3tui.tui.ui.button import Button
from q3tui.tui.ui.choice import Checkbox, RadioGroup, RadioGroupItem
from q3tui.tui.ui.field import FieldDescription, FieldError
from q3tui.tui.ui.input import Input
from q3tui.tui.ui.progress import Progress

__all__ = ["Question", "QuestionChoice", "Questionnaire"]

_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass
class QuestionChoice:
    label: str
    value: str = ""
    description: str = ""


@dataclass
class Question:
    """One question. `choices` may be plain strings. `multiple` lets several be chosen, `freeform`
    adds a text field for another answer, `skippable` adds a Skip action, and `required=False`
    lets the question go unanswered without skipping."""

    id: str
    title: str
    choices: list[QuestionChoice | str] = field(default_factory=list)
    description: str = ""
    multiple: bool = False
    freeform: bool = False
    skippable: bool = False
    required: bool = True

    def options(self) -> list[QuestionChoice]:
        return [QuestionChoice(c) if isinstance(c, str) else c for c in self.choices]


class Questionnaire(Vertical):
    """`Questionnaire(Question("lang", "Favorite language?", ["Python", "Rust"]), ...)`.

    Shows one question at a time with "Question 2 of 3" and a progress bar. Choices are keyed
    **A, B, C...**: the letter picks (or toggles) a choice from anywhere, and the arrow keys move
    through a single-choice list. **Alt+Right** goes on (Submit on the last question), **Alt+Left**
    goes back, and **Alt+S** skips a skippable question; each action shows its key. A required
    question that is unanswered shows an error instead of moving on. Posts `Questionnaire.Changed`
    on every answer and `Questionnaire.Submitted` at the end.

    `keys="local"`: the letters work only while the keyboard is in the questionnaire, so it can
    sit on a screen whose own keys are letters (the assistant panel, beside the review of Main).
    """

    DEFAULT_CSS = """
    Questionnaire { width: 1fr; height: auto; }
    Questionnaire > * { margin-bottom: 1; }
    Questionnaire > .q-title { text-style: bold; color: $foreground; height: auto; }
    Questionnaire > .q-actions { height: auto; align-horizontal: right; }
    Questionnaire > .q-actions > Button { margin-left: 2; }
    """

    class Changed(Message):
        def __init__(self, questionnaire: Questionnaire, answers: dict[str, object]) -> None:
            super().__init__()
            self.questionnaire = questionnaire
            self.answers = answers

        @property
        def control(self) -> Questionnaire:
            return self.questionnaire

    class Submitted(Message):
        def __init__(self, questionnaire: Questionnaire, answers: dict[str, object]) -> None:
            super().__init__()
            self.questionnaire = questionnaire
            self.answers = answers

        @property
        def control(self) -> Questionnaire:
            return self.questionnaire

    def __init__(
        self,
        *questions: Question,
        keys: Literal["screen", "local"] = "screen",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        if not questions:
            raise ValueError("A questionnaire needs at least one question")
        if keys not in ("screen", "local"):
            raise ValueError(f"Unknown questionnaire keys: {keys!r}")
        self.keys = keys
        if keys == "local":  # bindings of an ancestor of the focus: they win over the screen's
            for n, letter in enumerate(_LETTERS):
                self._bindings.bind(letter, f"pick({n})", show=False)
        self.questions = questions
        self.index = 0
        self.answers: dict[str, object] = {}
        self.submitted = False

    @property
    def question(self) -> Question:
        return self.questions[self.index]

    async def on_mount(self) -> None:
        await self.show(0)

    async def show(self, index: int) -> None:
        self.index = index
        await self.remove_children()
        await self.mount(*self._build())
        first = next((w for w in self.walk_children() if w.can_focus), None)
        if first is not None:
            first.focus()

    # -- building -----------------------------------------------------------------------------
    def _build(self) -> list:
        q, total = self.question, len(self.questions)
        parts: list = [
            Static(f"Question {self.index + 1} of {total}", classes="q-count", markup=False),
            Progress(self.index + 1, total, show_value=False, classes="q-progress"),
            Static(q.title, classes="q-title", markup=False),
        ]
        if q.description:
            parts.append(FieldDescription(q.description))
        options = q.options()
        picked = self.answers.get(q.id)
        known = {c.value or c.label for c in options}
        if q.multiple:
            chosen = set(picked) if isinstance(picked, list) else set()
            boxes = [
                self._keyed(
                    Checkbox(
                        self._text(c),
                        value=c.value or c.label,
                        checked=(c.value or c.label) in chosen,
                        key=self._key(n),
                        classes="q-choice",
                    ),
                    n,
                )
                for n, c in enumerate(options)
            ]
            parts.append(Vertical(*boxes, classes="q-choices"))
        else:
            items = [
                self._keyed(RadioGroupItem(self._text(c), c.value or c.label, key=self._key(n)), n)
                for n, c in enumerate(options)
            ]
            value = picked if isinstance(picked, str) and picked in known else None
            parts.append(RadioGroup(*items, value=value, classes="q-choices"))
        if q.freeform:
            text = (
                picked
                if isinstance(picked, str) and picked not in {c.value or c.label for c in options}
                else ""
            )
            parts.append(Input(text, placeholder="Something else…", classes="q-freeform"))
        parts.append(FieldError(id="q-error"))
        actions = []
        if self.index > 0:
            actions.append(Button("Previous", variant="ghost", key="alt+left", classes="q-prev"))
        if q.skippable:
            actions.append(Button("Skip", variant="secondary", key="alt+s", classes="q-skip"))
        last = self.index == total - 1
        actions.append(Button("Submit" if last else "Next", key="alt+right", classes="q-next"))
        parts.append(Horizontal(*actions, classes="q-actions"))
        return parts

    def _key(self, n: int) -> str | None:
        return _LETTERS[n] if self.keys == "screen" else None

    def _keyed(self, choice, n: int):
        """A local letter is shown like a key (the questionnaire binds it, not the screen)."""
        if self.keys == "local":
            choice.hint = _LETTERS[n]
        return choice

    def action_pick(self, n: int) -> None:
        """A letter, with `keys="local"`: pick (or toggle) that choice."""
        choices = list(self.query(".q-choice")) or [
            item for group in self.query(RadioGroup) for item in group.items
        ]
        if n < len(choices) and not choices[n].disabled:
            choices[n].focus()
            choices[n].activate()

    @staticmethod
    def _text(choice: QuestionChoice) -> str:
        return f"{choice.label} — {choice.description}" if choice.description else choice.label

    # -- answers ------------------------------------------------------------------------------
    def _notify(self) -> None:
        self.post_message(self.Changed(self, dict(self.answers)))

    def on_radio_group_changed(self, event: RadioGroup.Changed) -> None:
        event.stop()
        self.answers[self.question.id] = event.value
        for box in self.query(".q-freeform"):
            box.value = ""
        self._clear_error()
        self._notify()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        chosen = [b.value for b in self.query(".q-choice") if getattr(b, "checked", False) is True]
        self.answers[self.question.id] = chosen
        self._clear_error()
        self._notify()

    def on_input_changed(self, event: TextualInput.Changed) -> None:
        if not event.input.has_class("q-freeform"):
            return
        event.stop()
        q = self.question
        text = event.value.strip()
        if q.multiple:
            current = [v for v in (self.answers.get(q.id) or []) if v in self._values()]
            self.answers[q.id] = [*current, text] if text else current
        elif text:
            self.answers[q.id] = text
            for group in self.query(RadioGroup):
                for item in group.items:
                    item.selected = False
                    item.refresh_label()
        elif self.answers.get(q.id) not in self._values():
            self.answers.pop(q.id, None)
        self._clear_error()
        self._notify()

    def _values(self) -> set[str]:
        return {c.value or c.label for c in self.question.options()}

    def _clear_error(self) -> None:
        for error in self.query(FieldError):
            error.set_text("")

    def answered(self) -> bool:
        value = self.answers.get(self.question.id)
        return bool(value)

    # -- navigation ---------------------------------------------------------------------------
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        classes = event.button.classes
        if "q-prev" in classes:
            await self.back()
        elif "q-skip" in classes:
            await self.skip()
        else:
            await self.advance()

    async def back(self) -> None:
        if self.index > 0:
            await self.show(self.index - 1)

    async def skip(self) -> None:
        if self.question.skippable:
            self.answers.pop(self.question.id, None)
            await self._move()

    async def advance(self) -> None:
        if self.question.required and not self.answered():
            for error in self.query(FieldError):
                error.set_text("Choose an answer to continue.")
            return
        await self._move()

    async def _move(self) -> None:
        if self.index == len(self.questions) - 1:
            self.submitted = True
            self.post_message(self.Submitted(self, dict(self.answers)))
        else:
            await self.show(self.index + 1)
