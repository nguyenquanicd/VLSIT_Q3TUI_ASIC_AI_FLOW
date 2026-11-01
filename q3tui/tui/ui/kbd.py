"""Kbd: a key drawn as a small key cap, following shadcn's Kbd and KbdGroup."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from q3tui.tui.ui.icons import key_label

__all__ = ["Kbd", "KbdGroup"]


class Kbd(Static):
    """A Textual key name (`ctrl+k`, `enter`) on a muted cap, drawn with `key_label()`."""

    DEFAULT_CSS = """
    Kbd { width: auto; height: 1; padding: 0 1; background: $panel; color: $foreground; }
    """

    def __init__(self, key: str, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(key_label(key), id=id, classes=classes, markup=False)
        self.shortcut = key


class KbdGroup(Horizontal):
    """Several keys pressed one after another, such as `KbdGroup("ctrl+k", "ctrl+b")`."""

    DEFAULT_CSS = """
    KbdGroup { width: auto; height: 1; }
    KbdGroup > Kbd { margin-right: 1; }
    KbdGroup > Kbd:last-child { margin-right: 0; }
    """

    def __init__(self, *keys: str, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.keys = keys

    def compose(self) -> ComposeResult:
        for key in self.keys:
            yield Kbd(key)
