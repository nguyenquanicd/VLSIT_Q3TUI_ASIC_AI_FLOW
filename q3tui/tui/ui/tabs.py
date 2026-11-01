"""Tabs, following shadcn's Tabs: a row of triggers and the content of the active one."""

from __future__ import annotations

from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName

__all__ = ["Tabs", "TabsContent", "TabsList", "TabsTrigger"]


class TabsTrigger(Action):
    """One tab. Only the active trigger is a Tab stop; the arrow keys move between them."""

    DEFAULT_CSS = """
    TabsTrigger { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    TabsTrigger:hover, TabsTrigger:focus { color: $foreground; text-style: underline; }
    TabsTrigger.-active { background: $surface; color: $foreground; text-style: bold; }
    TabsTrigger:disabled { opacity: 50%; }
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        *,
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

    def activate(self) -> None:
        tabs = next((a for a in self.ancestors if isinstance(a, Tabs)), None)
        if tabs is not None:
            tabs.select(self.value)


class TabsList(Horizontal):
    DEFAULT_CSS = "TabsList { width: auto; height: 1; background: $panel; }"


class TabsContent(Vertical):
    """The content shown while the tab named `value` is active."""

    DEFAULT_CSS = "TabsContent { height: auto; margin-top: 1; }"

    def __init__(self, value: str, *children: Widget, id: str | None = None) -> None:
        super().__init__(*children, id=id)
        self.value = value


class Tabs(Vertical):
    """`Tabs(TabsList(TabsTrigger("Account", "account"), ...), TabsContent("account", ...))`.

    Left and Right move to the previous or next enabled tab and show it, wrapping around; Home and
    End go to the first and last. Posts `Tabs.Changed`.
    """

    DEFAULT_CSS = "Tabs { height: auto; }"
    BINDINGS = [
        Binding("left", "step(-1)", show=False),
        Binding("right", "step(1)", show=False),
        Binding("home", "edge(0)", show=False),
        Binding("end", "edge(-1)", show=False),
    ]

    class Changed(Message):
        def __init__(self, tabs: Tabs, value: str) -> None:
            super().__init__()
            self.tabs = tabs
            self.value = value

        @property
        def control(self) -> Tabs:
            return self.tabs

    def __init__(
        self,
        *parts: Widget,
        value: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*parts, id=id, classes=classes)
        self._initial = value
        self.value = ""

    @property
    def triggers(self) -> list[TabsTrigger]:
        return list(self.query(TabsTrigger))

    def on_mount(self) -> None:
        enabled = [t for t in self.triggers if not t.disabled]
        first = (
            self._initial if self._initial is not None else (enabled[0].value if enabled else "")
        )
        self.select(first, notify=False)

    def select(self, value: str, *, focus: bool = False, notify: bool = True) -> None:
        if value not in {t.value for t in self.triggers}:
            raise ValueError(f"Unknown tab: {value!r}")
        changed = value != self.value
        self.value = value
        for trigger in self.triggers:
            active = trigger.value == value
            trigger.set_class(active, "-active")
            trigger.can_focus = active and not trigger.disabled
        for content in self.query(TabsContent):
            content.display = content.value == value
        if focus:
            next(t for t in self.triggers if t.value == value).focus()
        if changed and notify:
            self.post_message(self.Changed(self, value))

    def action_step(self, direction: int) -> None:
        enabled = [t for t in self.triggers if not t.disabled]
        focused = self.screen.focused
        if focused not in enabled:
            raise SkipAction()
        self.select(enabled[(enabled.index(focused) + direction) % len(enabled)].value, focus=True)

    def action_edge(self, index: int) -> None:
        enabled = [t for t in self.triggers if not t.disabled]
        if self.screen.focused not in enabled:
            raise SkipAction()
        self.select(enabled[index].value, focus=True)
