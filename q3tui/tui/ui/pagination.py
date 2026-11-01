"""Pagination, following shadcn's Pagination: previous, page numbers, next."""

from __future__ import annotations

from textual import events
from textual.actions import SkipAction
from textual.binding import Binding
from textual.content import Content
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from q3tui.tui.ui.icons import icon

__all__ = ["Pagination", "page_window"]


def page_window(page: int, pages: int, neighbours: int = 1) -> list[int | None]:
    """The page numbers to show: the ends, the current page and its neighbours, and `None` for each
    gap. A gap of one page shows that page instead. `page_window(5, 10)` is
    `[1, None, 4, 5, 6, None, 10]`."""
    shown = sorted({1, pages, *range(max(1, page - neighbours), min(pages, page + neighbours) + 1)})
    out: list[int | None] = []
    previous: int | None = None
    for number in shown:
        if previous is not None:
            gap = number - previous
            if gap == 2:
                out.append(previous + 1)
            elif gap > 2:
                out.append(None)
        out.append(number)
        previous = number
    return out


class Pagination(Static, can_focus=True):
    """One Tab stop. Left/Right (or PageUp/PageDown) change the page by one, Home and End go to
    the first and last. A click on a number or an arrow goes there. Posts `Pagination.Changed`."""

    DEFAULT_CSS = """
    Pagination { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    Pagination:focus { text-style: underline; }
    """
    BINDINGS = [
        Binding("left,pageup", "turn(-1)", show=False),
        Binding("right,pagedown", "turn(1)", show=False),
        Binding("home", "go(1)", show=False),
        Binding("end", "go(-1)", show=False),
    ]

    page = reactive(1)

    class Changed(Message):
        def __init__(self, pagination: Pagination, page: int) -> None:
            super().__init__()
            self.pagination = pagination
            self.page = page

        @property
        def control(self) -> Pagination:
            return self.pagination

    def __init__(
        self,
        page: int = 1,
        pages: int = 1,
        *,
        neighbours: int = 1,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, markup=False)
        if pages < 1:
            raise ValueError("Pagination needs at least one page")
        self.pages = pages
        self.neighbours = neighbours
        self._hits: list[tuple[int, int, int]] = []  # (start, end, page) in cells
        self.set_reactive(Pagination.page, max(1, min(pages, page)))

    def on_mount(self) -> None:
        self._draw()

    def watch_page(self) -> None:
        if self.is_mounted:
            self._draw()

    def _draw(self) -> None:
        parts: list[str | tuple[str, str]] = []
        self._hits = []
        column = 1  # The padding.

        def add(text: str, style: str | None, target: int | None) -> None:
            nonlocal column
            parts.append((text, style) if style else text)
            if target is not None:
                self._hits.append((column, column + len(text), target))
            column += len(text)

        add(icon("chevron_left"), None if self.page > 1 else "dim", max(1, self.page - 1))
        for number in page_window(self.page, self.pages, self.neighbours):
            add(" ", None, None)
            if number is None:
                add(icon("ellipsis"), "dim", None)
            else:
                add(str(number), "bold reverse" if number == self.page else None, number)
        add(" ", None, None)
        add(
            icon("chevron_right"),
            None if self.page < self.pages else "dim",
            min(self.pages, self.page + 1),
        )
        self.update(Content.assemble(*parts))

    def go(self, page: int, *, notify: bool = True) -> None:
        page = max(1, min(self.pages, page))
        if page != self.page:
            self.page = page
            if notify:
                self.post_message(self.Changed(self, page))

    def action_turn(self, direction: int) -> None:
        if self.pages == 1:
            raise SkipAction()
        self.go(self.page + direction)

    def action_go(self, page: int) -> None:
        self.go(self.pages if page < 0 else page)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        for start, end, target in self._hits:
            if start <= event.x < end:
                self.go(target)
                return
