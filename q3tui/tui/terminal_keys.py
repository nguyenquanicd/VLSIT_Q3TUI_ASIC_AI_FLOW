"""Compatibility for legacy terminal Alt sequences in Textual 8.x."""

from collections.abc import Callable

from textual._ansi_sequences import ANSI_SEQUENCES_KEYS


def enable_alt_menu_keys() -> Callable[[], None]:
    """Let ESC+f decode as Alt+F instead of the legacy word-forward alias.

    Textual's parser table is shared by its Windows and POSIX drivers. Remove
    only this alias for the app lifetime; the actual Ctrl+Right escape sequence
    remains unchanged. Without the alias, the parser's normal Alt handling is
    used, just as for Alt+E/V/H. Restore the table on shutdown.
    """
    sequence = "\x1bf"
    original = ANSI_SEQUENCES_KEYS.pop(sequence, None)

    def restore() -> None:
        if original is not None:
            ANSI_SEQUENCES_KEYS.setdefault(sequence, original)

    return restore
