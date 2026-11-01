"""Label and Field, following shadcn's Label and Field."""

from __future__ import annotations

from typing import Literal

from textual import events
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

__all__ = [
    "Field",
    "FieldDescription",
    "FieldError",
    "FieldGroup",
    "FieldLabel",
    "Label",
]


class Label(Static):
    """Text that names a control. Clicking it focuses the control `for_` names (a CSS selector).
    A required label ends with a `*`."""

    DEFAULT_CSS = "Label { width: auto; height: 1; text-style: bold; color: $foreground; }"

    def __init__(
        self,
        text: str,
        *,
        for_: str | None = None,
        required: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(f"{text} *" if required else text, id=id, classes=classes, markup=False)
        self.for_ = for_

    def on_click(self, event: events.Click) -> None:
        if not self.for_:
            return
        event.stop()
        target = self.screen.query_one(self.for_)
        focusable = (
            target
            if target.can_focus
            else next((w for w in target.walk_children() if w.can_focus), None)
        )
        if focusable is not None:
            focusable.focus()


class FieldLabel(Label):
    """The label of a `Field`; it targets the field's control by itself."""


class FieldDescription(Static):
    DEFAULT_CSS = "FieldDescription { height: auto; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class FieldError(Static):
    """The error text. Empty text hides it."""

    DEFAULT_CSS = "FieldError { height: auto; color: $text-error; }"

    def __init__(self, text: str = "", *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)
        self.display = bool(text)

    def set_text(self, text: str) -> None:
        self.update(text)
        self.display = bool(text)


class Field(Vertical):
    """A label, a control, a description, and an error. `set_error("...")` shows the error and
    marks the field `-invalid`; `set_error(None)` clears it. A `horizontal` field puts the
    label and control on one row (for checkboxes and switches)."""

    DEFAULT_CSS = """
    Field { width: 1fr; height: auto; }
    Field.-horizontal { layout: horizontal; }
    Field.-horizontal > * { width: auto; margin-right: 1; }
    """

    def __init__(
        self,
        *parts: Widget,
        orientation: Literal["vertical", "horizontal"] = "vertical",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*parts, id=id, classes=classes)
        self.set_class(orientation == "horizontal", "-horizontal")

    def on_mount(self) -> None:
        control = self.control
        for label in self.query(FieldLabel):
            if label.for_ is None and control is not None:
                label.for_ = f"#{control.id}" if control.id else None

    @property
    def control(self) -> Widget | None:
        """The first child that is not a label, description, or error."""
        plain = (Label, FieldDescription, FieldError)
        return next((w for w in self.children if not isinstance(w, plain)), None)

    def set_error(self, message: str | None) -> None:
        self.set_class(bool(message), "-invalid")
        for error in self.query(FieldError):
            error.set_text(message or "")
        control = self.control
        if control is not None:
            control.set_class(bool(message), "-invalid")


class FieldGroup(Vertical):
    """Fields stacked with a blank row between them."""

    DEFAULT_CSS = """
    FieldGroup { width: 1fr; height: auto; }
    FieldGroup > Field { margin-bottom: 1; }
    FieldGroup > Field:last-child { margin-bottom: 0; }
    """
