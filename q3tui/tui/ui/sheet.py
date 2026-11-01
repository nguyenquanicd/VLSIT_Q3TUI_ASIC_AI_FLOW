"""Sheet: a panel that slides in from an edge of the screen, following shadcn's Sheet."""

from __future__ import annotations

from typing import Literal

from textual.widget import Widget

from q3tui.tui.ui.dialog import (
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
)

__all__ = [
    "Sheet",
    "SheetClose",
    "SheetDescription",
    "SheetFooter",
    "SheetHeader",
    "SheetTitle",
]

SheetHeader = DialogHeader
SheetTitle = DialogTitle
SheetDescription = DialogDescription
SheetFooter = DialogFooter
SheetClose = DialogClose


class Sheet(Dialog):
    """A `Dialog` docked to the `left`, `right`, `top`, or `bottom` edge and as tall (or wide) as
    the screen. `size` is its width for left and right, and its height for top and bottom. It
    takes the same parts and options as a `Dialog` and returns values the same way.
    """

    def __init__(
        self,
        *parts: Widget,
        side: Literal["left", "right", "top", "bottom"] = "right",
        size: int = 44,
        show_close_button: bool = True,
        dismiss_on_outside_click: bool = True,
        initial_focus: str | None = None,
    ) -> None:
        if side not in ("left", "right", "top", "bottom"):
            raise ValueError("Sheet side must be left, right, top, or bottom")
        super().__init__(
            *parts,
            show_close_button=show_close_button,
            dismiss_on_outside_click=dismiss_on_outside_click,
            initial_focus=initial_focus,
        )
        self.side = side
        self.size_cells = size

    def on_mount(self) -> None:
        super().on_mount()
        content = self.query_one(DialogContent)
        sideways = self.side in ("left", "right")
        content.styles.max_width = "100%"
        content.styles.max_height = "100%"
        content.styles.width = self.size_cells if sideways else "100%"
        content.styles.height = "100%" if sideways else self.size_cells
        content.styles.border_top = ("none", content.styles.background)
        content.styles.border_bottom = ("none", content.styles.background)
        horizontal = {"left": "left", "right": "right"}.get(self.side, "center")
        vertical = {"top": "top", "bottom": "bottom"}.get(self.side, "top")
        self.styles.align = (horizontal, vertical)
