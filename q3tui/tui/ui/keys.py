"""Screen-wide key bindings for widgets that are not in the focus chain.

Textual only looks at bindings of the focused widget, its ancestors, the screen, and the app.
A button that wants "press Ctrl+S from anywhere on this screen" therefore registers a binding
on its screen. A focused widget that uses the same key keeps it: the screen is the last stop.
"""

from __future__ import annotations

from collections.abc import Callable

from textual.widget import Widget

__all__ = ["bind_key"]


def bind_key(widget: Widget, key: str, callback: Callable[[], object]) -> Callable[[], None]:
    """Run `callback` when `key` is pressed anywhere on `widget`'s screen.

    Returns a function that removes the binding; call it when the widget unmounts.
    """
    screen = widget.screen
    action = f"widget_key_{id(widget):x}_{key.replace('+', '_')}"
    setattr(screen, f"action_{action}", callback)
    screen._bindings.bind(key, action, show=False)

    def unbind() -> None:
        bindings = screen._bindings.key_to_bindings.get(key, [])
        screen._bindings.key_to_bindings[key] = [b for b in bindings if b.action != action]
        if hasattr(screen, f"action_{action}"):
            delattr(screen, f"action_{action}")

    return unbind
