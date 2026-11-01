"""Toast: a short message in a corner that goes away, following shadcn's Toast and Sonner."""

from __future__ import annotations

from textual.containers import Vertical
from textual.timer import Timer
from textual.widget import Widget

from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle, AlertVariant
from q3tui.tui.ui.menu import background_beneath

__all__ = ["Toast", "Toaster", "toast"]


class Toast(Alert):
    """An `Alert` that removes itself after `duration` seconds (never, if `duration` is 0)."""

    DEFAULT_CSS = "Toast { width: 1fr; margin-top: 0; }"

    def __init__(
        self,
        title: str,
        description: str = "",
        *,
        variant: AlertVariant = "default",
        duration: float = 4.0,
    ) -> None:
        parts = [AlertTitle(title)]
        if description:
            parts.append(AlertDescription(description))
        super().__init__(*parts, variant=variant)
        self.duration = duration
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        if self.duration:
            self._timer = self.set_timer(self.duration, self.dismiss)

    async def dismiss(self) -> None:
        toaster = self.parent
        if self.is_attached:
            await self.remove()
        if isinstance(toaster, Toaster):
            toaster.refit()


class Toaster(Vertical):
    """Stacks toasts at the bottom-right of the screen, newest at the bottom. It lives on the
    Screen above everything else, shows at most `limit` toasts, and takes no focus."""

    DEFAULT_CSS = """
    Toaster { overlay: screen; position: absolute; constrain: inside inside; width: 42;
        height: auto; background: transparent; }
    """
    can_focus = False

    def __init__(self, limit: int = 3) -> None:
        super().__init__()
        self.limit = limit

    async def add(self, item: Toast) -> None:
        await self.mount(item)
        extra = list(self.query(Toast))[: -self.limit]
        for old in extra:
            await old.dismiss()
        self.refit()

    def refit(self) -> None:
        """Show or hide the stack and put it in the corner, after the next layout."""
        self.display = bool(self.query(Toast))
        self.call_after_refresh(self._place)

    def _place(self) -> None:
        if not self.is_attached:  # its screen went away (a switch) before the layout settled
            return
        screen = self.screen.size
        size = self.outer_size
        self.styles.offset = (
            max(0, screen.width - size.width - 1),
            max(0, screen.height - size.height - 1),
        )
        for item in self.query(Toast):
            item.styles.border_top = ("outer", background_beneath(item, item.region.y))
            item.styles.border_bottom = ("outer", background_beneath(item, item.region.bottom - 1))

    async def clear(self) -> None:
        for item in list(self.query(Toast)):
            await item.dismiss()


async def toast(
    where: Widget,
    title: str,
    description: str = "",
    *,
    variant: AlertVariant = "default",
    duration: float = 4.0,
) -> Toast:
    """Show a toast on the screen `where` belongs to, creating the `Toaster` the first time."""
    screen = where.screen
    toaster = next(iter(screen.query(Toaster)), None)
    if toaster is None:
        toaster = Toaster()
        await screen.mount(toaster)
    item = Toast(title, description, variant=variant, duration=duration)
    await toaster.add(item)
    return item
