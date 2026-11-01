"""Alt+<key> from a terminal (ESC then the key) reaches Q3TUI as alt+<key> (q3tui/tui/terminal_keys.py)."""

import pytest
from textual._xterm_parser import XTermParser

from q3tui.tui.terminal_keys import enable_alt_menu_keys


def keys(data: str) -> list[str]:
    p = XTermParser(debug=False)
    return [e.key for e in [*p.feed(data), *p.feed("")] if hasattr(e, "key")]


@pytest.fixture
def patched():
    restore = enable_alt_menu_keys()
    yield
    restore()


@pytest.mark.parametrize("seq,key", [("\x1b1", "alt+1"), ("\x1b4", "alt+4"), ("\x1b,", "alt+comma"), ("\x1bf", "alt+f"),
                                     ("\x1bb", "alt+b"), ("\x1br", "alt+r"), ("\x1bh", "alt+h")])
def test_alt_keys(patched, seq, key):
    assert keys(seq) == [key]


@pytest.mark.parametrize("seq,key", [("\x1b", "escape"), (",", "comma"), ("1", "1"), ("\x1b[Z", "shift+tab"),
                                     ("\x1b[1;5C", "ctrl+right"), ("\x1bOQ", "f2")])
def test_other_keys_unchanged(patched, seq, key):
    assert keys(seq) == [key]


def test_restore():
    restore = enable_alt_menu_keys()
    restore()
    assert keys("\x1b1") != ["alt+1"]
