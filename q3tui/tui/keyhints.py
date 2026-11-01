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
    keys = _hints(screen, focused)
    tabs = _find(focused, "Tabs")
    if tabs is not None:  # Alt+<n>: a tab of the tab component around the focus
        n = len([t for t in tabs.triggers if not t.disabled])
        keys.insert(len(keys) - 1 if keys and keys[-1][0] == "tab" else len(keys), (f"alt+1…{n}", "tab"))
    return keys


def _hints(screen, focused: Widget | None) -> list[tuple[str, str]]:
    kind = type(screen).__name__
    move = [("tab", "next part")]
    if _find(focused, "Menubar"):
        return [("←→", "menu"), ("enter", "open"), ("escape", "back"), *move]
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
                return [("↑↓", "move"), ("enter", "fold"), ("←→", "close / open"), ("shift+f10", "menu"), *move]
            display = row.status.display if row.status else None
            return [("↑↓", "move"), ("enter", "view"), *_step_keys(display), ("shift+f10", "menu"), *move]
        main = _find(focused, "StepMain")
        if main is not None and main.step:
            ops = screen.app.opened.ops
            display = ops.status(main.step).display if ops else None
            group = _find(focused, "ItemList")
            fid = getattr(group, "id", "") or ""
            if group is not None and fid != "list-questions":
                keys = [("↑↓", "item"), ("c", "confirm"), ("shift+c", "all"), ("w", "change it"), ("m", "ask")]
            elif group is not None:
                keys = [("↑↓", "question"), ("enter", "answer")]
            elif type(focused).__name__ == "Button":
                keys = [("enter", "press")]
            elif type(focused).__name__ == "EventLine":
                keys = [("enter", "open / close")]
            else:
                keys = [("←→", "tab")]
            step = [k for k in _step_keys(display) if k[0] in ("a", "shift+a", "q", "r")]
            return [*keys, *step, *move]
        if _find(focused, "Activities"):
            fold = [("enter", "open / close")] if type(focused).__name__ == "EventLine" else []
            return [*fold, ("↑↓", "scroll"), ("ctrl+end", "latest"), *move]
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
            return [("enter", "send"), ("shift+enter", "new line"), *move]
        return [("escape", "back"), ("ctrl+f", "search"), *move]
    return move


def focus_label(screen, focused: Widget | None) -> str:
    """What has the focus, in a few words, shown before the keys: `Flow ▸ spec`, `Main ▸ spec ▸ Log`, `Activities`."""
    if focused is None:
        return ""
    if _find(focused, "Menubar"):
        label = str(getattr(focused, "label_text", "") or "").strip()
        return f"Menubar ▸ {label}" if label else "Menubar"
    if _find(focused, "TitleBar"):
        return "Title bar"
    kind = type(screen).__name__
    if kind == "HomeScreen":
        if _find(focused, "PromptBox"):
            return "Input"
        alerts = _find(focused, "AlertList")
        if alerts is not None:
            items = alerts.items
            return f"Alerts ▸ {alerts.index + 1}/{len(items)}" if items else "Alerts"
    if kind == "WorkspaceScreen":
        if _find(focused, "ChatInput"):
            return "Assistant ▸ input"
        if _find(focused, "ChatPanel"):
            return "Assistant"
        row = _find(focused, "FlowRow")
        if row is not None:
            return f"Flow ▸ {'stage ' if row.kind == 'stage' else ''}{row.ident}"
        if _find(focused, "FlowTree") or _find(focused, "TabsTrigger") and _find(focused, "ResizablePanel"):
            return "Flow"
        main = _find(focused, "StepMain")
        if main is not None:
            tabs = main.query("Tabs")
            tab = tabs.first().value.removeprefix("view-") if tabs else ""
            return " ▸ ".join(x for x in ("Main", main.step or "", tab) if x)
        if _find(focused, "Activities"):
            return "Activities"
    if kind == "SettingsScreen":
        if getattr(focused, "id", "") == "search":
            return "Settings ▸ search"
        row = _find(focused, "SettingRow")
        if row is not None:
            return f"Settings ▸ {row.config_layer} ▸ {row.key.dotted}"
        if _find(focused, "ChatPanel"):
            return "Assistant"
        return "Settings"
    return type(focused).__name__
