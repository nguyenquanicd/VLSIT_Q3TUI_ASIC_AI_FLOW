"""The keys of the moment, shown in the status bar: they follow the focus (spec/tui.md "Rules" 5)."""

from __future__ import annotations

from textual.widget import Widget


def _within(widget: Widget | None, name: str) -> bool:
    node = widget
    while node is not None:
        if type(node).__name__ == name:
            return True
        node = node.parent
    return False


def hints(screen, focused: Widget | None) -> list[tuple[str, str]]:
    """What the keys do where the focus is, the most useful first; then the screen's general keys."""
    kind = type(screen).__name__
    general = [("ctrl+r", "run"), ("ctrl+k", "commands"), ("f1", "keys")]
    if kind == "HomeScreen":
        alerts = bool(screen.query("AlertList"))
        if _within(focused, "PromptBox"):
            keys = [("enter", "write the file"), ("shift+enter", "new line")]
            return keys + ([("tab", "alerts")] if alerts else []) + general
        if _within(focused, "AlertList"):
            return [("↑↓", "choose"), ("enter", "open"), ("shift+tab", "input")] + general
        return ([("tab", "alerts")] if alerts else []) + general + [("alt+comma", "settings")]
    if kind == "WorkspaceScreen":
        if _within(focused, "ChatInput"):
            return [("enter", "send"), ("shift+enter", "new line"), ("/", "commands"), ("escape", "stop"),
                    ("ctrl+l", "new chat")]
        if _within(focused, "ChatPanel"):
            return [("alt+1", "type"), ("ctrl+l", "new chat")] + general
        if _within(focused, "FlowTree"):
            row = focused if type(focused).__name__ == "FlowRow" else None
            if row is not None and row.kind == "stage":
                return [("↑↓", "move"), ("enter", "fold"), ("left", "close"), ("right", "open"), ("s", "run")] \
                    + general
            return [("enter", "view"), ("t", "run to"), ("o", "only"), ("f", "from"), (".", "again"), ("a", "approve"),
                    ("r", "change"), ("q", "answer")] + general
        if _within(focused, "StepMain"):
            if _within(focused, "ItemList"):
                return [("↑↓", "item"), ("c", "confirm"), ("shift+c", "all"), ("w", "change item"),
                        ("m", "ask"), ("[ ]", "tab"), ("a", "approve")] + general
            return [("[ ]", "tab"), ("a", "approve"), ("r", "change"), ("q", "answer"), ("t", "run to")] + general
        if _within(focused, "Activities"):
            return [("↑↓", "scroll"), ("ctrl+end", "latest")] + general
        return [("alt+1", "assistant"), ("alt+2", "flow"), ("alt+3", "main"), ("alt+4", "activities")] + general
    if kind == "SettingsScreen":
        if _within(focused, "SettingRow"):
            return [("enter", "save"), ("tab", "next"), ("ctrl+f", "search"), ("escape", "back")]
        return [("ctrl+f", "search"), ("tab", "next"), ("escape", "back")]
    return general
