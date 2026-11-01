"""Collapsible and Accordion, following shadcn: sections that open and close."""

from __future__ import annotations

from typing import Literal

from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName

__all__ = [
    "Accordion",
    "AccordionItem",
    "Collapsible",
    "CollapsibleContent",
    "CollapsibleTrigger",
]


class CollapsibleTrigger(Action):
    """The heading. Enter, Space, a click, or its key opens and closes the section; the chevron
    shows which."""

    DEFAULT_CSS = """
    CollapsibleTrigger { width: 1fr; height: 1; padding: 0 1; color: $foreground; }
    CollapsibleTrigger:hover, CollapsibleTrigger:focus { background: $panel; }
    CollapsibleTrigger:disabled { opacity: 50%; }
    """

    def glyph_name(self) -> IconName | None:
        section = next((a for a in self.ancestors if isinstance(a, Collapsible)), None)
        return "chevron_down" if section is not None and section.open else "chevron_right"

    def activate(self) -> None:
        section = next((a for a in self.ancestors if isinstance(a, Collapsible)), None)
        if section is not None:
            section.set_open(not section.open)


class CollapsibleContent(Vertical):
    DEFAULT_CSS = "CollapsibleContent { height: auto; padding: 0 3; }"


class Collapsible(Vertical):
    """`Collapsible(CollapsibleTrigger("Details"), CollapsibleContent(...), open=False)`."""

    DEFAULT_CSS = "Collapsible { height: auto; }"

    class Toggled(Message):
        def __init__(self, collapsible: Collapsible, open: bool) -> None:
            super().__init__()
            self.collapsible = collapsible
            self.open = open

        @property
        def control(self) -> Collapsible:
            return self.collapsible

    def __init__(
        self,
        *parts: Widget,
        open: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*parts, id=id, classes=classes)
        self.open = open

    def on_mount(self) -> None:
        self._apply()

    def _apply(self) -> None:
        for content in self.query(CollapsibleContent):
            content.display = self.open
        for trigger in self.query(CollapsibleTrigger):
            trigger.refresh_label()

    def set_open(self, open: bool, *, notify: bool = True) -> None:
        if open == self.open:
            return
        self.open = open
        self._apply()
        if notify:
            self.post_message(self.Toggled(self, open))


class AccordionItem(Collapsible):
    """A titled section: `AccordionItem("Is it accessible?", Static("Yes."), value="a11y")`."""

    DEFAULT_CSS = "AccordionItem { margin-bottom: 1; }"

    def __init__(
        self,
        title: str,
        *content: Widget,
        value: str = "",
        open: bool = False,
        key: str | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            CollapsibleTrigger(title, key=key, disabled=disabled),
            CollapsibleContent(*content),
            open=open,
            id=id,
            classes=classes,
        )
        self.value = value or title


class Accordion(Vertical):
    """Items stacked. `single`: opening one closes the others, and with `collapsible=False` the
    open one cannot be closed. `multiple`: any number open. Up and Down move between the headings,
    Home and End go to the first and last."""

    DEFAULT_CSS = (
        "Accordion { height: auto; } Accordion > AccordionItem:last-child { margin-bottom: 0; }"
    )
    BINDINGS = [
        Binding("up", "step(-1)", show=False),
        Binding("down", "step(1)", show=False),
        Binding("home", "edge(0)", show=False),
        Binding("end", "edge(-1)", show=False),
    ]

    def __init__(
        self,
        *items: AccordionItem,
        type: Literal["single", "multiple"] = "single",
        collapsible: bool = True,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*items, id=id, classes=classes)
        if type not in ("single", "multiple"):
            raise ValueError("Accordion type must be single or multiple")
        self.type = type
        self.collapsible = collapsible

    @property
    def items(self) -> list[AccordionItem]:
        return list(self.query(AccordionItem))

    @property
    def value(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.items if item.open)

    def on_mount(self) -> None:
        if self.type == "single":
            seen = False
            for item in self.items:
                if item.open and seen:
                    item.set_open(False, notify=False)
                seen = seen or item.open

    def on_collapsible_toggled(self, event: Collapsible.Toggled) -> None:
        item = event.collapsible
        if not isinstance(item, AccordionItem):
            return
        if self.type == "single" and event.open:
            for other in self.items:
                if other is not item:
                    other.set_open(False, notify=False)
        elif self.type == "single" and not self.collapsible and not self.value:
            item.set_open(True, notify=False)

    def _triggers(self) -> list[CollapsibleTrigger]:
        return [t for t in self.query(CollapsibleTrigger) if not t.disabled]

    def action_step(self, direction: int) -> None:
        triggers, focused = self._triggers(), self.screen.focused
        if focused not in triggers:
            raise SkipAction()
        triggers[(triggers.index(focused) + direction) % len(triggers)].focus()

    def action_edge(self, index: int) -> None:
        triggers = self._triggers()
        if self.screen.focused not in triggers:
            raise SkipAction()
        triggers[index].focus()
