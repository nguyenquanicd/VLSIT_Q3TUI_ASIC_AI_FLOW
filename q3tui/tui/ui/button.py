"""Button, ButtonGroup, Toggle, and ToggleGroup, following shadcn and made key-first.

Every action can have a `key`: it works from anywhere on the screen, and is shown after the
label as key icons, the way the prompt shows its submit key.
"""

from __future__ import annotations

from typing import Literal

from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.timer import Timer

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName

__all__ = ["Button", "ButtonGroup", "Toggle", "ToggleGroup"]

ButtonVariant = Literal["default", "secondary", "destructive", "outline", "ghost", "link"]
_SPINNER: tuple[IconName, ...] = (
    "spinner_1",
    "spinner_2",
    "spinner_3",
    "spinner_4",
    "spinner_5",
    "spinner_6",
)


class Button(Action):
    """One row, one cell of padding for the text. Enter or Space presses it when focused.

    `loading=True` shows a spinner and ignores presses. Variants: `default`, `secondary`,
    `destructive`, `outline` (underlined text), `ghost` (fills on hover), and `link`.
    """

    DEFAULT_CSS = """
    Button { width: auto; height: 1; padding: 0 1; background: $primary; color: $background; }
    Button:hover, Button:focus { text-style: bold underline; }
    Button.-secondary { background: $panel; color: $foreground; }
    Button.-destructive { background: $error; color: $background; }
    Button.-outline { background: transparent; color: $foreground; text-style: underline; }
    Button.-ghost { background: transparent; color: $foreground; }
    Button.-ghost:hover, Button.-ghost:focus { background: $panel; }
    Button.-link { background: transparent; color: $primary; text-style: underline; }
    Button:disabled { opacity: 50%; }
    Button.-loading { opacity: 70%; }
    """

    class Pressed(Message):
        def __init__(self, button: Button) -> None:
            super().__init__()
            self.button = button

        @property
        def control(self) -> Button:
            return self.button

    def __init__(
        self,
        label: str,
        *,
        variant: ButtonVariant = "default",
        key: str | None = None,
        icon_name: IconName | None = None,
        loading: bool = False,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            label, key=key, icon_name=icon_name, disabled=disabled, id=id, classes=classes
        )
        self.variant = variant
        self.busy = loading  # Not `loading`: Textual's Widget already has that.
        self._frame = 0
        self._spin: Timer | None = None
        if variant != "default":
            self.add_class(f"-{variant}")

    def on_mount(self) -> None:
        super().on_mount()
        self.set_loading(self.busy)

    def glyph_name(self) -> IconName | None:
        if self.busy:
            return _SPINNER[self._frame % len(_SPINNER)]
        return super().glyph_name()

    def set_loading(self, loading: bool) -> None:
        self.busy = loading
        self.set_class(loading, "-loading")
        if self._spin:
            self._spin.stop()
            self._spin = None
        if loading:
            self._spin = self.set_interval(0.12, self._tick)
        self.refresh_label()

    def _tick(self) -> None:
        self._frame += 1
        self.refresh_label()

    def activate(self) -> None:
        if not self.busy:
            self.post_message(self.Pressed(self))


class ButtonGroup(Horizontal):
    """Buttons side by side. Left and Right move focus along the group (Up and Down when
    vertical)."""

    DEFAULT_CSS = """
    ButtonGroup { width: auto; height: 1; }
    ButtonGroup > Action { margin-right: 1; }
    ButtonGroup > Action:last-child { margin-right: 0; }
    ButtonGroup.-vertical { layout: vertical; height: auto; }
    ButtonGroup.-vertical > Action { margin-right: 0; }
    """
    BINDINGS = [
        Binding("left", "step(-1, 'x')", show=False),
        Binding("right", "step(1, 'x')", show=False),
        Binding("up", "step(-1, 'y')", show=False),
        Binding("down", "step(1, 'y')", show=False),
    ]

    def __init__(
        self,
        *buttons: Action,
        orientation: Literal["horizontal", "vertical"] = "horizontal",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*buttons, id=id, classes=classes)
        self.orientation = orientation
        self.set_class(orientation == "vertical", "-vertical")

    def action_step(self, direction: int, axis: str) -> None:
        items = [w for w in self.query(Action) if not w.disabled]
        focused = self.screen.focused
        if axis != ("y" if self.orientation == "vertical" else "x") or focused not in items:
            raise SkipAction()  # Let the key reach whatever else wants it.
        items[(items.index(focused) + direction) % len(items)].focus()


class Toggle(Action):
    """A button that stays pressed. Space or Enter flips it; `key` flips it from anywhere."""

    DEFAULT_CSS = """
    Toggle { width: auto; height: 1; padding: 0 1; background: transparent;
        color: $text-muted; }
    Toggle:hover, Toggle:focus { color: $foreground; text-style: underline; }
    Toggle.-pressed { background: $primary-muted; color: $foreground; text-style: bold; }
    Toggle.-outline { text-style: underline; }
    Toggle:disabled { opacity: 50%; }
    """

    class Changed(Message):
        def __init__(self, toggle: Toggle, pressed: bool) -> None:
            super().__init__()
            self.toggle = toggle
            self.pressed = pressed
            self.value = toggle.value

        @property
        def control(self) -> Toggle:
            return self.toggle

    def __init__(
        self,
        label: str,
        *,
        value: str = "",
        pressed: bool = False,
        variant: Literal["default", "outline"] = "default",
        key: str | None = None,
        icon_name: IconName | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            label, key=key, icon_name=icon_name, disabled=disabled, id=id, classes=classes
        )
        self.value = value or label
        self.pressed = pressed
        self.set_class(pressed, "-pressed")
        if variant == "outline":
            self.add_class("-outline")

    def set_pressed(self, pressed: bool, *, notify: bool = True) -> None:
        if pressed == self.pressed:
            return
        self.pressed = pressed
        self.set_class(pressed, "-pressed")
        if notify:
            self.post_message(self.Changed(self, pressed))

    def activate(self) -> None:
        self.set_pressed(not self.pressed)


class ToggleGroup(Horizontal):
    """Toggles that share a value. `single`: at most one is pressed (pressing it again
    clears it). `multiple`: any number. Left and Right move focus along the group."""

    DEFAULT_CSS = """
    ToggleGroup { width: auto; height: 1; }
    ToggleGroup > Toggle { margin-right: 1; }
    ToggleGroup > Toggle:last-child { margin-right: 0; }
    """
    BINDINGS = [
        Binding("left", "step(-1)", show=False),
        Binding("right", "step(1)", show=False),
    ]

    class Changed(Message):
        def __init__(self, group: ToggleGroup, value: str | tuple[str, ...] | None) -> None:
            super().__init__()
            self.group = group
            self.value = value

        @property
        def control(self) -> ToggleGroup:
            return self.group

    def __init__(
        self,
        *toggles: Toggle,
        type: Literal["single", "multiple"] = "single",
        value: str | tuple[str, ...] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*toggles, id=id, classes=classes)
        if type not in ("single", "multiple"):
            raise ValueError("ToggleGroup type must be single or multiple")
        self.type = type
        wanted = (value,) if isinstance(value, str) else tuple(value or ())
        for toggle in toggles:
            toggle.set_pressed(toggle.value in wanted, notify=False)
        if type == "single":
            seen = False
            for toggle in toggles:
                if toggle.pressed and seen:
                    toggle.set_pressed(False, notify=False)
                seen = seen or toggle.pressed

    @property
    def value(self) -> str | tuple[str, ...] | None:
        pressed = tuple(t.value for t in self.query(Toggle) if t.pressed)
        if self.type == "multiple":
            return pressed
        return pressed[0] if pressed else None

    def on_toggle_changed(self, event: Toggle.Changed) -> None:
        event.stop()
        if self.type == "single" and event.pressed:
            for toggle in self.query(Toggle):
                if toggle is not event.toggle:
                    toggle.set_pressed(False, notify=False)
        self.post_message(self.Changed(self, self.value))

    def action_step(self, direction: int) -> None:
        items = [t for t in self.query(Toggle) if not t.disabled]
        focused = self.screen.focused
        if focused not in items:
            raise SkipAction()
        items[(items.index(focused) + direction) % len(items)].focus()
