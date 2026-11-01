"""Resizable panels, following shadcn's Resizable: panes whose divider can be moved."""

from __future__ import annotations

from typing import Literal

from textual import events
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

__all__ = ["ResizableHandle", "ResizablePanel", "ResizablePanelGroup"]


class ResizablePanel(Vertical):
    """One pane. `size` is its share of the group (relative to the others), and `min_size` the
    smallest share, as a percentage of the group, it can shrink to."""

    DEFAULT_CSS = "ResizablePanel { height: 1fr; width: 1fr; }"

    def __init__(
        self,
        *children: Widget,
        size: float = 50,
        min_size: float = 10,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*children, id=id, classes=classes)
        self.size_share = size
        self.min_share = min_size


class ResizableHandle(Static, can_focus=True):
    """The divider. Focus it and press the arrow keys (the ones along the group) to move it by one
    cell, Shift plus the arrow by five, Home and End to push it to either end. Drag it with the
    mouse."""

    DEFAULT_CSS = """
    ResizableHandle { background: transparent; border-left: solid $foreground 30%; }
    ResizableHandle:hover, ResizableHandle:focus { border-left: solid $primary; }
    """
    BINDINGS = [
        Binding("left", "move(-1, 'x')", show=False),
        Binding("right", "move(1, 'x')", show=False),
        Binding("up", "move(-1, 'y')", show=False),
        Binding("down", "move(1, 'y')", show=False),
        Binding("shift+left", "move(-5, 'x')", show=False),
        Binding("shift+right", "move(5, 'x')", show=False),
        Binding("shift+up", "move(-5, 'y')", show=False),
        Binding("shift+down", "move(5, 'y')", show=False),
        Binding("home", "edge(-1)", show=False),
        Binding("end", "edge(1)", show=False),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("", id=id)
        self.dragging = False

    @property
    def group(self) -> ResizablePanelGroup | None:
        return next((a for a in self.ancestors if isinstance(a, ResizablePanelGroup)), None)

    def action_move(self, cells: int, axis: str) -> None:
        group = self.group
        along = "x" if group is None or group.direction == "horizontal" else "y"
        if group is None or axis != along:
            raise SkipAction()  # An arrow across the group is not ours.
        group.move_handle(self, cells)

    def action_edge(self, direction: int) -> None:
        group = self.group
        if group is None:
            raise SkipAction()
        group.move_handle(self, direction * 10_000)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.dragging = True
        self.capture_mouse()
        self.focus()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.dragging = False
        self.release_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        group = self.group
        if self.dragging and group is not None:
            group.drag_handle(self, event.screen_x, event.screen_y)


class ResizablePanelGroup(Horizontal):
    """`ResizablePanelGroup(ResizablePanel(...), ResizableHandle(), ResizablePanel(...))`.

    `direction="horizontal"` puts the panels side by side, `"vertical"` stacks them. Handles sit
    between panels; moving one trades space between its two neighbours, never below their
    `min_size`.
    """

    DEFAULT_CSS = """
    ResizablePanelGroup { width: 1fr; height: 1fr; }
    ResizablePanelGroup.-vertical { layout: vertical; }
    ResizablePanelGroup > ResizableHandle { width: 1; height: 1fr; }
    ResizablePanelGroup.-vertical > ResizableHandle { width: 1fr; height: 1;
        border-left: none; border-top: solid $foreground 30%; }
    ResizablePanelGroup.-vertical > ResizableHandle:hover,
    ResizablePanelGroup.-vertical > ResizableHandle:focus { border-top: solid $primary; }
    """

    def __init__(
        self,
        *parts: Widget,
        direction: Literal["horizontal", "vertical"] = "horizontal",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*parts, id=id, classes=classes)
        if direction not in ("horizontal", "vertical"):
            raise ValueError("Resizable direction must be horizontal or vertical")
        self.direction = direction
        self.set_class(direction == "vertical", "-vertical")

    @property
    def panels(self) -> list[ResizablePanel]:
        return [c for c in self.children if isinstance(c, ResizablePanel)]

    @property
    def visible_panels(self) -> list[ResizablePanel]:
        return [p for p in self.panels if p.display]

    def on_mount(self) -> None:
        self._apply()

    def _apply(self) -> None:
        for panel in self.panels:
            weight = max(1, round(panel.size_share * 100))
            if self.direction == "horizontal":
                panel.styles.width = f"{weight}fr"
            else:
                panel.styles.height = f"{weight}fr"

    def _extent(self, widget: Widget) -> int:
        region = widget.region
        return region.width if self.direction == "horizontal" else region.height

    def _total_cells(self) -> int:
        return sum(self._extent(panel) for panel in self.visible_panels)

    def _neighbours(self, handle: ResizableHandle) -> tuple[ResizablePanel, ResizablePanel] | None:
        children = list(self.children)
        index = children.index(handle)
        before, after = children[index - 1], children[index + 1]
        if isinstance(before, ResizablePanel) and isinstance(after, ResizablePanel):
            return before, after
        return None

    def _share_per_cell(self) -> float:
        return sum(p.size_share for p in self.visible_panels) / max(1, self._total_cells())

    def _place(self, before: ResizablePanel, after: ResizablePanel, share: float) -> None:
        """Give `before` this share of the group, taking it from or handing it to `after`, never
        taking either below its `min_size`."""
        total_share = sum(p.size_share for p in self.visible_panels)
        pair = before.size_share + after.size_share
        low = before.min_share * total_share / 100
        high = pair - after.min_share * total_share / 100
        moved = max(low, min(high, share))
        before.size_share, after.size_share = moved, pair - moved
        self._apply()

    def move_handle(self, handle: ResizableHandle, cells: int) -> None:
        """Move `handle` by `cells` toward the end (negative: toward the start)."""
        panels = self._neighbours(handle)
        if panels is not None:
            before, after = panels
            self._place(before, after, before.size_share + cells * self._share_per_cell())

    def drag_handle(self, handle: ResizableHandle, x: int, y: int) -> None:
        """Put the divider under the pointer. The size is worked out from the pointer position, not
        from how far the panel has moved: mouse moves arrive faster than the layout settles, so a
        step measured against the stale panel region would be applied twice."""
        panels = self._neighbours(handle)
        if panels is None:
            return
        before, after = panels
        region = before.region
        horizontal = self.direction == "horizontal"
        extent = (x - region.x) if horizontal else (y - region.y)
        self._place(before, after, max(0, extent) * self._share_per_cell())
