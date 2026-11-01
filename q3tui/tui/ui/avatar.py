"""Avatar: initials on a colored chip, following shadcn's Avatar and AvatarGroup.

A terminal has no images, so only the fallback form exists.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

__all__ = ["Avatar", "AvatarGroup", "initials"]

_COLORS = 6


def initials(name: str) -> str:
    """`Ada Lovelace` -> `AL`, `plato` -> `PL`, an empty name -> `?`."""
    words = name.split()
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


class Avatar(Static):
    """The same name always gets the same one of six theme-muted colors."""

    DEFAULT_CSS = """
    Avatar { width: auto; height: 1; padding: 0 1; color: $foreground; }
    Avatar.-c0 { background: $primary-muted; }
    Avatar.-c1 { background: $secondary-muted; }
    Avatar.-c2 { background: $accent-muted; }
    Avatar.-c3 { background: $success-muted; }
    Avatar.-c4 { background: $warning-muted; }
    Avatar.-c5 { background: $error-muted; }
    """

    def __init__(self, name: str, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(initials(name), id=id, classes=classes, markup=False)
        self.person = name
        self.add_class(f"-c{sum(map(ord, name)) % _COLORS}")


class AvatarGroup(Horizontal):
    """Avatars side by side, one cell apart."""

    DEFAULT_CSS = """
    AvatarGroup { width: auto; height: 1; }
    AvatarGroup > Avatar { margin-right: 1; }
    AvatarGroup > Avatar:last-child { margin-right: 0; }
    """

    def __init__(self, *names: str, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.names = names

    def compose(self) -> ComposeResult:
        for name in self.names:
            yield Avatar(name)
