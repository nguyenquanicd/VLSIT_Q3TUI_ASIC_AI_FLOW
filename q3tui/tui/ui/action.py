"""Action: the shared base of Button, Toggle, Checkbox, Switch, and the radio items."""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.content import Content
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon, key_label
from q3tui.tui.ui.keys import bind_key

__all__ = ["Action"]


class Action(Static, can_focus=True):
    """A focusable one-row label with an icon, a key hint, and a screen-wide key.

    Subclasses say what activating it does (`activate`) and which icon shows (`glyph`)."""

    BINDINGS = [Binding("enter,space", "press", "Press", show=False)]

    def __init__(
        self,
        label: str = "",
        *,
        key: str | None = None,
        hint: str | None = None,
        icon_name: IconName | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled, markup=False)
        self.label = label
        self.shortcut = key
        self.hint = hint  # Shown like a key, but bound by whoever owns it (a local binding).
        self.icon_name = icon_name
        self._unbind = None

    def on_mount(self) -> None:
        if self.shortcut:
            self._unbind = bind_key(self, self.shortcut, self._press_from_key)
        self.refresh_label()

    def on_unmount(self) -> None:
        if self._unbind:
            self._unbind()

    def set_label(self, label: str) -> None:
        self.label = label
        self.refresh_label()

    def refresh_label(self) -> None:
        parts: list[str | tuple[str, str]] = []
        glyph = self.glyph()
        if glyph:
            parts += [glyph, " "]
        parts.append(self.label)
        shown = self.shortcut or self.hint
        if shown:
            parts += [" ", (key_label(shown), "dim")]
        self.update(Content.assemble(*parts))

    def glyph_name(self) -> IconName | None:
        return self.icon_name

    def glyph(self) -> str:
        name = self.glyph_name()
        return icon(name) if name else ""

    def activate(self) -> None:
        raise NotImplementedError

    def action_press(self) -> None:
        if not self.disabled:
            self.activate()

    def _press_from_key(self) -> None:
        if self.is_attached and not self.disabled:
            self.activate()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if not self.disabled:
            self.focus()
            self.activate()
