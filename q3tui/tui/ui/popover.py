"""Popover: a floating box of widgets anchored to a trigger, following shadcn's Popover."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from textual import events
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.menu import background_beneath

__all__ = ["Popover", "PopoverContent", "PopoverTrigger"]


class PopoverTrigger(Action):
    """The button that opens the popover. Enter, Space, a click, or its key toggles it."""

    DEFAULT_CSS = """
    PopoverTrigger { width: auto; height: 1; padding: 0 1; background: $panel; color: $foreground; }
    PopoverTrigger:hover, PopoverTrigger:focus { text-style: bold underline; }
    PopoverTrigger.-open { background: $primary-muted; }
    """

    def activate(self) -> None:
        popover = next((a for a in self.ancestors if isinstance(a, Popover)), None)
        if popover is not None:
            self.app.call_later(popover.toggle)


class PopoverContent(Vertical):
    """The box. It lives on the Screen, so its widgets' messages bubble to the Screen, not to
    the `Popover`. Escape closes it."""

    DEFAULT_CSS = """
    PopoverContent { overlay: screen; position: absolute; constrain: inside inside;
        width: auto; min-width: 16; max-width: 50; height: auto; padding: 0 1;
        background: $surface; color: $foreground;
        border-top: outer $background; border-bottom: outer $background; }
    """
    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, owner: Popover, *parts: Widget) -> None:
        super().__init__(*parts)
        self.owner = owner

    async def action_close(self) -> None:
        await self.owner.close(restore_focus=True)

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        # The box is mounted on the Screen, so the Popover never sees its widgets lose focus.
        self.owner.call_after_refresh(self.owner._maybe_close)


class Popover(Vertical):
    """`Popover(PopoverTrigger("Dimensions"), Input(), Button("Apply"), side="bottom")`.

    Opening moves focus to the first focusable widget inside, or leaves it on the trigger when
    there is none. Escape closes it and returns focus to the trigger; a click outside, or moving
    focus elsewhere, closes it too. It opens below the trigger (`side="top"` for above), flips
    when there is no room, and is left-aligned with the trigger (`align="end"` right-aligns it).
    """

    DEFAULT_CSS = "Popover { width: auto; height: 1; }"

    class Toggled(Message):
        def __init__(self, popover: Popover, open: bool) -> None:
            super().__init__()
            self.popover = popover
            self.open = open

        @property
        def control(self) -> Popover:
            return self.popover

    def __init__(
        self,
        trigger: PopoverTrigger | str,
        *parts: Widget,
        side: Literal["top", "bottom"] = "bottom",
        align: Literal["start", "end"] = "start",
        factory: Callable[[], Sequence[Widget]] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.trigger = PopoverTrigger(trigger) if isinstance(trigger, str) else trigger
        super().__init__(self.trigger, id=id, classes=classes)
        self.parts = parts
        self.factory = factory  # Builds fresh content each time it opens, instead of `parts`.
        self.side = side
        self.align = align
        self.content: PopoverContent | None = None

    @property
    def is_open(self) -> bool:
        return self.content is not None

    def on_mount(self) -> None:
        self.app.message_signal.subscribe(self, self._observe)

    async def on_unmount(self) -> None:
        self.app.message_signal.unsubscribe(self)
        await self.close()

    async def _observe(self, message: Message) -> None:
        if isinstance(message, events.MouseDown) and self.content is not None:
            point = (message.screen_x, message.screen_y)
            if not self.content.region.contains(*point) and not self.trigger.region.contains(
                *point
            ):
                await self.close()
        elif isinstance(message, events.Resize):
            await self.close()

    async def open(self) -> None:
        if self.content is not None:
            return
        self.content = PopoverContent(self, *(self.factory() if self.factory else self.parts))
        self.trigger.add_class("-open")
        await self.screen.mount(self.content)
        self.call_after_refresh(self._place)
        self.post_message(self.Toggled(self, True))

    def _place(self) -> None:
        box = self.content
        if box is None or not box.is_mounted:
            return
        anchor, size, screen = self.trigger.region, box.outer_size, self.screen.size
        x = anchor.x if self.align == "start" else anchor.right - size.width
        below = anchor.bottom
        above = anchor.y - size.height
        wants_top = self.side == "top"
        y = above if wants_top and above >= 0 else below
        if y + size.height > screen.height and above >= 0:
            y = above
        box.styles.offset = (
            max(0, min(x, screen.width - size.width)),
            max(0, min(y, screen.height - size.height)),
        )
        self.call_after_refresh(self._edges)
        focusable = next((w for w in box.walk_children() if w.can_focus), None)
        if focusable is not None:
            focusable.focus()

    def _edges(self) -> None:
        box = self.content
        if box is not None and box.is_mounted:
            box.styles.border_top = ("outer", background_beneath(box, box.region.y))
            box.styles.border_bottom = ("outer", background_beneath(box, box.region.bottom - 1))

    async def close(self, *, restore_focus: bool = False) -> None:
        box, self.content = self.content, None
        if box is None:
            return
        self.trigger.remove_class("-open")
        if box.is_mounted:
            await box.remove()
        if restore_focus:
            self.trigger.focus()
        self.post_message(self.Toggled(self, False))

    async def toggle(self) -> None:
        if self.content is None:
            await self.open()
        else:
            await self.close(restore_focus=True)

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self.call_after_refresh(self._maybe_close)

    async def _maybe_close(self) -> None:
        box = self.content
        focused = self.screen.focused
        if (
            box is not None
            and focused is not None
            and not (focused is self.trigger or box in focused.ancestors_with_self)
        ):
            await self.close()
