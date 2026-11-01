"""Badge: a short status label, following shadcn's Badge."""

from __future__ import annotations

from typing import Literal

from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Badge"]

BadgeVariant = Literal["default", "secondary", "destructive", "outline", "success", "warning"]


class Badge(Static):
    """One row, one cell of padding on each side. `success` and `warning` are additions."""

    DEFAULT_CSS = """
    Badge { width: auto; height: 1; padding: 0 1; background: $primary; color: $background; }
    Badge.-secondary { background: $panel; color: $foreground; }
    Badge.-destructive { background: $error; color: $background; }
    Badge.-success { background: $success; color: $background; }
    Badge.-warning { background: $warning; color: $background; }
    Badge.-outline { background: transparent; color: $foreground; text-style: underline; }
    """

    def __init__(
        self,
        label: str,
        *,
        variant: BadgeVariant = "default",
        icon_name: IconName | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        text = f"{icon(icon_name)} {label}" if icon_name else label
        super().__init__(text, id=id, classes=classes, markup=False)
        self.variant = variant
        if variant != "default":
            self.add_class(f"-{variant}")
