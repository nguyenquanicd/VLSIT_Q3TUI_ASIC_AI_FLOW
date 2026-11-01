"""What every screen of Q3TUI shares: the focus starts on its main part; Tab / Shift+Tab move the focus between
its parts, the title bar first; Escape on the title bar (no menu open) goes back to the main part; the keys of the
status bar follow the focus."""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.screen import Screen
from textual.widget import Widget


def in_title_bar(widget: Widget) -> bool:
    node = widget
    while node is not None:
        if type(node).__name__ == "TitleBar":
            return True
        node = node.parent
    return False


class PartScreen(Screen):
    BINDINGS = [Binding("tab", "move_focus(1)", show=False), Binding("shift+tab", "move_focus(-1)", show=False)]

    def main_part(self) -> Widget | None:
        """The widget the focus starts on."""
        return None

    def on_mount(self) -> None:
        self.call_after_refresh(self.focus_main)

    def focus_main(self) -> None:
        main = self.main_part()
        if main is not None and main.focusable:
            main.focus()
        self.app.refresh_keys()

    def on_descendant_focus(self) -> None:
        self.remember_focus()
        self.app.refresh_keys()

    def parts(self) -> list[Widget]:
        """The parts Tab moves between after the title bar (each takes the focus on its first focusable widget, or
        the one it had); none: every focusable widget, in order."""
        return []

    def _all_parts(self) -> list[Widget]:
        parts = self.parts()
        if not parts:
            return []
        return [*self.query("TitleBar Menubar"), *parts]

    def on_key(self, event: events.Key) -> None:
        """Escape on the title bar, with no menu open: back to the main part."""
        if event.key != "escape" or self.focused is None or not in_title_bar(self.focused):
            return
        if any(getattr(root, "popups", None) for root in self.query("TitleBar MenuRoot")):
            return
        event.stop()
        event.prevent_default()
        self.focus_main()

    def action_move_focus(self, step: int) -> None:
        here = self.focused
        parts = [p for p in self._all_parts() if p.display and any(w.focusable for w in p.query("*")) or p.focusable]
        if parts:
            at = next((n for n, p in enumerate(parts) if here is not None and (here is p or p in here.ancestors)), -1)
            target = parts[(at + step) % len(parts)] if at >= 0 else parts[0 if step > 0 else -1]
            last = getattr(target, "_q3_last_focus", None)
            chosen = target.focus_target() if hasattr(target, "focus_target") else None
            if chosen is not None and chosen.focusable:
                chosen.focus()
            elif last is not None and last.is_attached and last.focusable:
                last.focus()
            elif target.focusable:
                target.focus()
            else:
                next(w for w in target.query("*") if w.focusable).focus()
            return
        chain = list(self.focus_chain)
        if not chain:
            return
        if here not in chain:
            chain[0 if step > 0 else -1].focus()
            return
        chain[(chain.index(here) + step) % len(chain)].focus()

    def remember_focus(self) -> None:
        """Each part remembers its last focused widget, so Tab comes back to it."""
        here = self.focused
        if here is None:
            return
        for part in self._all_parts():
            if here is part or part in here.ancestors:
                part._q3_last_focus = here
