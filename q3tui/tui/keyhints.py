"""The keys of the status bar: only those of the part that has the focus, and only the ones that work there now
(spec/tui.md "Rules" 5)."""

from __future__ import annotations

from textual.widget import Widget


def _find(widget: Widget | None, name: str) -> Widget | None:
    node = widget
    while node is not None:
        if type(node).__name__ == name:
            return node
        node = node.parent
    return None


def _step_keys(display: str | None) -> list[tuple[str, str]]:
    """The keys of a step, by its display state (a key that would be refused is not shown)."""
    keys = [("t", "run to"), ("o", "only"), ("f", "from"), ("s", "stage")]
    if display in ("done", "approved", "stale", "approval waiting", "question waiting"):
        keys.append((".", "again"))
    if display == "approval waiting":
        keys += [("a", "approve"), ("shift+a", "force")]
    if display == "question waiting":
        keys.append(("q", "answer"))
    if display in ("done", "approved", "approval waiting"):
        keys.append(("r", "change"))
    return keys


def hints(screen, focused: Widget | None) -> list[tuple[str, str]]:
    kind = type(screen).__name__
    move = [("tab", "next part")]
    if kind == "HomeScreen":
        if _find(focused, "PromptBox"):
            return [("enter", "write the file"), ("shift+enter", "new line"), *move]
        if _find(focused, "AlertList"):
            return [("↑↓", "choose"), ("space", "open"), ("shift+tab", "input")]
        return move
    if kind == "WorkspaceScreen":
        chat = _find(focused, "ChatPanel")
        if _find(focused, "ChatInput"):
            keys = [("enter", "send"), ("shift+enter", "new line"), ("/", "commands")]
            if chat is not None and chat.busy:
                keys.append(("escape", "stop"))
            return [*keys, ("ctrl+l", "new chat"), *move]
        if chat is not None:
            return [("ctrl+l", "new chat"), *move]
        row = _find(focused, "FlowRow")
        if row is not None:
            if row.kind == "stage":
                return [("↑↓", "move"), ("enter", "fold"), ("←→", "close / open"), *move]
            display = row.status.display if row.status else None
            return [("↑↓", "move"), ("enter", "view"), *_step_keys(display), *move]
        main = _find(focused, "StepMain")
        if main is not None and main.step:
            ops = screen.app.opened.ops
            display = ops.status(main.step).display if ops else None
            fid = getattr(focused, "id", "") or ""
            if _find(focused, "ItemList") is not None and fid != "list-questions":
                keys = [("↑↓", "item"), ("c", "confirm"), ("shift+c", "all"), ("w", "change it"), ("m", "ask")]
            elif fid == "list-questions":
                keys = [("↑↓", "question"), ("enter", "answer")]
            elif type(focused).__name__ == "Button":
                keys = [("enter", "press")]
            else:
                keys = [("←→", "tab")]
            step = [k for k in _step_keys(display) if k[0] in ("a", "shift+a", "q", "r")]
            return [*keys, ("[ ]", "tab"), *step, *move]
        if _find(focused, "Activities"):
            return [("↑↓", "scroll"), ("ctrl+end", "latest"), *move]
        return move
    if kind == "SettingsScreen":
        if getattr(focused, "id", "") == "search":
            return [("enter", "search"), ("escape", "back"), *move]
        if _find(focused, "SettingRow"):
            if type(focused).__name__ == "Select":
                return [("enter", "choose"), ("escape", "back"), *move]
            if type(focused).__name__ == "Button":
                return [("enter", "press"), ("escape", "back"), *move]
            return [("enter", "save"), ("escape", "back"), ("ctrl+f", "search"), *move]
        if _find(focused, "ChatInput"):
            return [("enter", "send"), ("shift+enter", "new line"), ("alt+1", "hide assistant"), *move]
        return [("escape", "back"), ("ctrl+f", "search"), ("alt+1", "assistant"), *move]
    return move
