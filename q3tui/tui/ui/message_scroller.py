"""MessageScroller, following shadcn's Message Scroller: a transcript that follows its live edge."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from q3tui.tui.ui.action import Action

__all__ = ["MessageScroller", "MessageScrollerButton"]


class MessageScrollerButton(Action):
    """The "Latest" button: shown while the reader is away from the end of the transcript."""

    DEFAULT_CSS = """
    MessageScrollerButton { width: auto; height: 1; padding: 0 1; background: $panel;
        color: $foreground; }
    MessageScrollerButton:hover, MessageScrollerButton:focus { text-style: bold underline; }
    """

    def activate(self) -> None:
        scroller = next((a for a in self.ancestors if isinstance(a, MessageScroller)), None)
        if scroller is not None:
            scroller.jump_to_end()


class _Viewport(VerticalScroll):
    DEFAULT_CSS = "_Viewport { layer: base; width: 1fr; height: 1fr; }"

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        scroller = self.parent
        if isinstance(scroller, MessageScroller):
            scroller.note_scrolled()


class MessageScroller(Vertical):
    """A transcript. New items (`add`) scroll into view while the reader is at the end; scroll up
    and it stops following and shows a "Latest" button (Ctrl+End jumps to the end, and following
    resumes). `prepend` loads earlier messages without moving what is on screen, and
    `scroll_to_item` brings one into view.

    The viewport is a scrolling container, so it takes the arrow keys, PageUp and PageDown, Home and
    End when focused.
    """

    DEFAULT_CSS = """
    MessageScroller { layers: base overlay; align: right bottom; height: 1fr; }
    MessageScroller > MessageScrollerButton { layer: overlay; margin: 0 1 1 0; display: none; }
    MessageScroller.-away > MessageScrollerButton { display: block; }
    """

    following = reactive(True)

    def __init__(
        self,
        *items: Widget,
        jump_key: str = "ctrl+end",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._initial = items
        self.jump_key = jump_key

    @property
    def viewport(self) -> VerticalScroll:
        return self.query_one(_Viewport)

    def compose(self) -> ComposeResult:
        with _Viewport():
            yield from self._initial
        yield MessageScrollerButton("Latest", icon_name="arrow_down", key=self.jump_key)

    def on_mount(self) -> None:
        self.call_after_refresh(self.jump_to_end)

    @property
    def at_end(self) -> bool:
        view = self.viewport
        return view.scroll_y >= view.max_scroll_y - 1

    def note_scrolled(self) -> None:
        self.following = self.at_end
        self.set_class(not self.following, "-away")

    async def add(self, *items: Widget) -> None:
        """Append items; follow them when the reader is at the end."""
        was_following = self.following
        await self.viewport.mount(*items)
        if was_following:
            self.call_after_refresh(self.jump_to_end)

    async def prepend(self, *items: Widget) -> None:
        """Insert items before the first one and keep the visible messages where they were."""
        view = self.viewport
        before_height, before_y = view.virtual_size.height, view.scroll_y
        first = view.children[0] if view.children else None
        if first is not None:
            await view.mount(*items, before=first)
        else:
            await view.mount(*items)
        self.call_after_refresh(self._keep_place, before_height, before_y)

    def _keep_place(self, before_height: int, before_y: float) -> None:
        if not self.query(_Viewport):  # removed before the refresh came (a view rebuilt)
            return
        view = self.viewport
        view.scroll_to(y=before_y + (view.virtual_size.height - before_height), animate=False)

    def jump_to_end(self) -> None:
        if not self.query(_Viewport):  # removed before the refresh came (a view rebuilt)
            return
        self.viewport.scroll_end(animate=False)
        self.following = True
        self.set_class(False, "-away")

    def scroll_to_item(self, item: Widget) -> None:
        self.viewport.scroll_to_widget(item, animate=False, top=True)
