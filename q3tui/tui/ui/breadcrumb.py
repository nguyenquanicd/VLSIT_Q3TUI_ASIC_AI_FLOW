"""Breadcrumb, following shadcn's Breadcrumb: where you are, with links back up."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Breadcrumb", "BreadcrumbEllipsis", "BreadcrumbItem", "BreadcrumbPage"]


class BreadcrumbItem(Action):
    """A link to an ancestor. Enter, Space, or a click posts `Breadcrumb.Navigate`."""

    DEFAULT_CSS = """
    BreadcrumbItem { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    BreadcrumbItem:hover, BreadcrumbItem:focus { color: $foreground; text-style: underline; }
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        *,
        icon_name: IconName | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(label, icon_name=icon_name, id=id, classes=classes)
        self.value = value or label

    def activate(self) -> None:
        crumbs = next((a for a in self.ancestors if isinstance(a, Breadcrumb)), None)
        if crumbs is not None:
            crumbs.post_message(Breadcrumb.Navigate(crumbs, self.value))


class BreadcrumbPage(Static):
    """The current page: bold, not a link."""

    DEFAULT_CSS = "BreadcrumbPage { width: auto; height: 1; padding: 0 1; text-style: bold; }"

    def __init__(self, label: str, *, id: str | None = None) -> None:
        super().__init__(label, id=id, markup=False)


class BreadcrumbEllipsis(Static):
    """Stands in for hidden levels."""

    DEFAULT_CSS = "BreadcrumbEllipsis { width: auto; height: 1; padding: 0 1; color: $text-muted; }"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(icon("ellipsis"), id=id, markup=False)


class Breadcrumb(Horizontal):
    """`Breadcrumb(BreadcrumbItem("Home"), BreadcrumbItem("Docs"), BreadcrumbPage("Tabs"))`.

    A chevron separates the parts. Tab visits the links; Left and Right move between them.
    """

    DEFAULT_CSS = """
    Breadcrumb { width: auto; height: 1; }
    Breadcrumb > .breadcrumb-separator { width: 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("left", "step(-1)", show=False),
        Binding("right", "step(1)", show=False),
    ]

    class Navigate(Message):
        def __init__(self, breadcrumb: Breadcrumb, value: str) -> None:
            super().__init__()
            self.breadcrumb = breadcrumb
            self.value = value

        @property
        def control(self) -> Breadcrumb:
            return self.breadcrumb

    def __init__(self, *parts: Static | Action, id: str | None = None, classes: str | None = None):
        super().__init__(id=id, classes=classes)
        self.parts = parts

    def compose(self) -> ComposeResult:
        for index, part in enumerate(self.parts):
            if index:
                yield Static(icon("chevron_right"), classes="breadcrumb-separator", markup=False)
            yield part

    def action_step(self, direction: int) -> None:
        from textual.actions import SkipAction

        links = list(self.query(BreadcrumbItem))
        focused = self.screen.focused
        if focused not in links:
            raise SkipAction()
        links[(links.index(focused) + direction) % len(links)].focus()
