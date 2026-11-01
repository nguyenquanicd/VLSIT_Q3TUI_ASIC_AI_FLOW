"""AlertDialog: a confirmation that must be answered, following shadcn's Alert Dialog."""

from __future__ import annotations

from q3tui.tui.ui.dialog import (
    Dialog,
    DialogClose,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
)

__all__ = ["AlertDialog"]


class AlertDialog(Dialog):
    """Returns `True` for the action and `False` for cancel; Escape cancels.

    Unlike a plain `Dialog` it has no close glyph and a click outside does nothing, so the user
    has to choose. The action is bound to `action_key`: Enter by default, and `y` when
    `destructive=True` so a stray Enter cannot confirm it; a destructive dialog also starts with
    Cancel focused.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        *,
        action: str = "Continue",
        cancel: str = "Cancel",
        destructive: bool = False,
        action_key: str | None = None,
        width: int | None = None,
    ) -> None:
        key = action_key or ("y" if destructive else "enter")
        header = DialogHeader(
            DialogTitle(title), *([DialogDescription(description)] if description else [])
        )
        footer = DialogFooter(
            DialogClose(cancel, False, key="escape", id="alert-cancel"),
            DialogClose(
                action,
                True,
                key=key,
                variant="error" if destructive else "default",
                id="alert-action",
            ),
        )
        super().__init__(
            header,
            footer,
            show_close_button=False,
            dismiss_on_outside_click=False,
            initial_focus="#alert-cancel" if destructive else "#alert-action",
            width=width,
        )
