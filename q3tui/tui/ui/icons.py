"""Semantic icon names, drawn from one of two sets (`tui.icons`, spec/tui.md "Look"): Nerd Font glyphs (`nerd`, the
default) or plain Unicode for any font (`unicode`).

Nerd Font source: https://github.com/ryanoasis/nerd-fonts/blob/master/glyphnames.json
"""

from typing import Literal

IconName = Literal[
    "session_cost",
    "project_cost",
    "chevron_down",
    "flow",
    "model",
    "selected",
    "chevron_right",
    "mixed",
    "new_session",
    "quit",
    "prompt",
    "clear",
    "appearance",
    "about",
    "close",
    "calendar",
    "thumbs_up",
    "thumbs_down",
    "heart",
    "star",
    "copy",
    "trash",
    "arrow_down",
    "tool",
    "thought",
    "sparkle",
    "attach",
    "file",
    "file_code",
    "file_image",
    "done",
    "chevron_left",
    "ellipsis",
    "sidebar",
    "home",
    "checkbox_off",
    "checkbox_on",
    "checkbox_mixed",
    "switch_on",
    "switch_off",
    "radio_on",
    "radio_off",
    "search",
    "error",
    "warning",
    "inbox",
    "spinner_1",
    "spinner_2",
    "spinner_3",
    "spinner_4",
    "spinner_5",
    "spinner_6",
    "settings",
    "step_pending",
    "step_running",
    "step_done",
    "step_failed",
    "step_gate",
    "step_blocked",
    "gate_human",
    "gate_auto",
    "key_enter",
    "key_escape",
    "key_tab",
    "key_space",
    "key_backspace",
    "key_ctrl",
    "key_shift",
    "key_alt",
    "key_f1",
    "key_f2",
    "key_f3",
    "key_f4",
    "key_f5",
    "key_f6",
    "key_f7",
    "key_f8",
    "key_f9",
    "key_f10",
    "key_f11",
    "key_f12",
]

_NERD_FONTS: dict[IconName, str] = {
    "session_cost": "\uea82",  # nf-cod-history
    "project_cost": "\uea83",  # nf-cod-folder
    "chevron_down": "\ueab4",  # nf-cod-chevron_down
    "flow": "\ueafe",  # nf-cod-git_merge
    "model": "\ueb08",  # nf-cod-hubot
    "selected": "\ueab2",  # nf-cod-check
    "chevron_right": "\ueab6",  # nf-cod-chevron_right
    "mixed": "\ueb3b",  # nf-cod-remove
    "new_session": "\uea7f",  # nf-cod-new_file
    "quit": "\uea6e",  # nf-cod-sign_out
    "prompt": "\uea85",  # nf-cod-terminal
    "clear": "\ueabf",  # nf-cod-clear_all
    "appearance": "\ueb5c",  # nf-cod-symbol_color
    "about": "\uea74",  # nf-cod-info
    "close": "\uea76",  # nf-cod-close
    "calendar": "\ueab0",  # nf-cod-calendar
    "thumbs_up": "\ueb6c",  # nf-cod-thumbsup
    "thumbs_down": "\ueb6b",  # nf-cod-thumbsdown
    "heart": "\ueb05",  # nf-cod-heart
    "star": "\ueb59",  # nf-cod-star_full
    "copy": "\uebcc",  # nf-cod-copy
    "trash": "\uea81",  # nf-cod-trash
    "arrow_down": "\uea9a",  # nf-cod-arrow_down
    "tool": "\ueb6d",  # nf-cod-tools
    "thought": "\uea61",  # nf-cod-lightbulb
    "sparkle": "\uec10",  # nf-cod-sparkle
    "attach": "\uec34",  # nf-cod-attach
    "file": "\uea7b",  # nf-cod-file
    "file_code": "\ueae9",  # nf-cod-file_code
    "file_image": "\U000f021f",  # nf-md-file_image
    "done": "\ueba4",  # nf-cod-pass
    "chevron_left": "\ueab5",  # nf-cod-chevron_left
    "ellipsis": "\uea7c",  # nf-cod-ellipsis
    "sidebar": "\uebf3",  # nf-cod-layout_sidebar_left
    "home": "\ueb06",  # nf-cod-home
    "checkbox_off": "\U000f0131",  # nf-md-checkbox_blank_outline
    "checkbox_on": "\U000f0132",  # nf-md-checkbox_marked
    "checkbox_mixed": "\U000f0375",  # nf-md-minus_box
    "switch_on": "\U000f0521",  # nf-md-toggle_switch
    "switch_off": "\U000f0522",  # nf-md-toggle_switch_off
    "radio_on": "\U000f043e",  # nf-md-radiobox_marked
    "radio_off": "\U000f043d",  # nf-md-radiobox_blank
    "search": "\uea6d",  # nf-cod-search
    "error": "\uea87",  # nf-cod-error
    "warning": "\uea6c",  # nf-cod-warning
    "inbox": "\ueb09",  # nf-cod-inbox
    "spinner_1": "\uee06",  # nf-extra-progress_spinner_1
    "spinner_2": "\uee07",  # nf-extra-progress_spinner_2
    "spinner_3": "\uee08",  # nf-extra-progress_spinner_3
    "spinner_4": "\uee09",  # nf-extra-progress_spinner_4
    "spinner_5": "\uee0a",  # nf-extra-progress_spinner_5
    "spinner_6": "\uee0b",  # nf-extra-progress_spinner_6
    "settings": "\ueb51",  # nf-cod-settings_gear
    "step_pending": "\uebb5",  # nf-cod-circle_large
    "step_running": "\ueb19",  # nf-cod-loading
    "step_done": "\ueba4",  # nf-cod-pass
    "step_failed": "\uea87",  # nf-cod-error
    "step_gate": "\uead1",  # nf-cod-debug_pause
    "step_blocked": "\ueabd",  # nf-cod-circle_slash
    "gate_human": "\uea67",  # nf-cod-person
    "gate_auto": "\ueb2c",  # nf-cod-play
    "key_enter": "\U000f0311",  # nf-md-keyboard_return
    "key_escape": "\U000f12b7",  # nf-md-keyboard_esc
    "key_tab": "\U000f0312",  # nf-md-keyboard_tab
    "key_space": "\U000f1050",  # nf-md-keyboard_space
    "key_backspace": "\U000f030d",  # nf-md-keyboard_backspace
    "key_ctrl": "\U000f0634",  # nf-md-apple_keyboard_control
    "key_shift": "\U000f0636",  # nf-md-apple_keyboard_shift
    "key_alt": "\U000f0635",  # nf-md-apple_keyboard_option
    "key_f1": "\U000f12ab",  # nf-md-keyboard_f1
    "key_f2": "\U000f12ac",  # nf-md-keyboard_f2
    "key_f3": "\U000f12ad",  # nf-md-keyboard_f3
    "key_f4": "\U000f12ae",  # nf-md-keyboard_f4
    "key_f5": "\U000f12af",  # nf-md-keyboard_f5
    "key_f6": "\U000f12b0",  # nf-md-keyboard_f6
    "key_f7": "\U000f12b1",  # nf-md-keyboard_f7
    "key_f8": "\U000f12b2",  # nf-md-keyboard_f8
    "key_f9": "\U000f12b3",  # nf-md-keyboard_f9
    "key_f10": "\U000f12b4",  # nf-md-keyboard_f10
    "key_f11": "\U000f12b5",  # nf-md-keyboard_f11
    "key_f12": "\U000f12b6",  # nf-md-keyboard_f12
}


_UNICODE: dict[IconName, str] = {
    "session_cost": "$", "project_cost": "$", "chevron_down": "▾", "flow": "⑂", "model": "◆", "selected": "✓",
    "chevron_right": "▸", "mixed": "−", "new_session": "+", "quit": "⏻", "prompt": "›", "clear": "⌫",
    "appearance": "◐", "about": "ⓘ", "close": "✕", "calendar": "▦", "thumbs_up": "▲", "thumbs_down": "▼",
    "heart": "♥", "star": "★", "copy": "⧉", "trash": "✗", "arrow_down": "↓", "tool": "⚒", "thought": "✧",
    "sparkle": "✦", "attach": "⊕", "file": "▤", "file_code": "▤", "file_image": "▣", "done": "✓",
    "chevron_left": "◂", "ellipsis": "⋯", "sidebar": "▥", "home": "⌂", "checkbox_off": "☐", "checkbox_on": "☑",
    "checkbox_mixed": "⊟", "switch_on": "●", "switch_off": "○", "radio_on": "◉", "radio_off": "○", "search": "⌕",
    "error": "✖", "warning": "⚠", "inbox": "☐", "spinner_1": "⠋", "spinner_2": "⠙", "spinner_3": "⠹",
    "spinner_4": "⠸", "spinner_5": "⠼", "spinner_6": "⠴", "settings": "⚙", "step_pending": "○",
    "step_running": "◌", "step_done": "✓", "step_failed": "✖", "step_gate": "⏸", "step_blocked": "⊘",
    "gate_human": "☺", "gate_auto": "▶", "key_enter": "Enter", "key_escape": "Esc", "key_tab": "Tab",
    "key_space": "Space", "key_backspace": "Bksp", "key_ctrl": "Ctrl", "key_shift": "Shift", "key_alt": "Alt",
    **{f"key_f{i}": f"F{i}" for i in range(1, 13)},
}

ICON_SETS: dict[str, dict[IconName, str]] = {"nerd": _NERD_FONTS, "unicode": _UNICODE}
_current = {"set": "nerd"}


def set_icon_set(name: str) -> None:
    """Draw icons from `nerd` or `unicode` from now on (widgets drawn already keep theirs until redrawn)."""
    if name not in ICON_SETS:
        raise ValueError(f"icon set is one of {', '.join(ICON_SETS)}")
    _current["set"] = name


def icon_set() -> str:
    return _current["set"]


def icon(name: IconName) -> str:
    return ICON_SETS[_current["set"]][name]


_KEY_ICONS: dict[str, IconName] = {
    "enter": "key_enter",
    "escape": "key_escape",
    "tab": "key_tab",
    "space": "key_space",
    "backspace": "key_backspace",
    "ctrl": "key_ctrl",
    "shift": "key_shift",
    "alt": "key_alt",
    **{f"f{i}": f"key_f{i}" for i in range(1, 13)},
}


_KEY_TEXT = {"comma": ","}


def key_label(key: str) -> str:
    """Display form of a Textual key name: icons for keys that have one, text otherwise.

    `escape` -> the Esc icon, `ctrl+d` -> the Ctrl icon plus `D`, `f6` -> the F6 icon. Letters
    and digits stay text: they are easier to read than an icon.
    """
    return "+".join(
        icon(_KEY_ICONS[part])
        if part in _KEY_ICONS
        else part.upper()
        if len(part) == 1
        else _KEY_TEXT.get(part, part.title())
        for part in key.split("+")
    )
