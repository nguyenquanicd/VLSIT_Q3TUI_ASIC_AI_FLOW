"""The base of the TUI's dialogs: a modal screen that closes once."""

from __future__ import annotations

from typing import TypeVar

from textual.await_complete import AwaitComplete
from textual.screen import ModalScreen

R = TypeVar("R")


class Dialog(ModalScreen[R]):
    """A modal screen that closes once. A second Enter / click queued before the first one closed it (a busy TUI, a double
    click, key repeat) is ignored: dismissing it again would pop the screen under it (Textual's ScreenStackError, which
    ended the TUI and so its runs)."""

    _dismissed = False  # (not `_closed`: Textual's own, the screen's message loop stops on it)

    def dismiss(self, result: R | None = None) -> AwaitComplete:
        if self._dismissed:
            return AwaitComplete.nothing()
        self._dismissed = True
        return super().dismiss(result)
