"""Compatibility for legacy terminal Alt sequences in Textual 8.x.

A terminal sends Alt+<key> as ESC followed by the key. Textual 8 decodes some of these wrongly:

- ESC+f / ESC+b: the word-movement aliases ctrl+right / ctrl+left, not alt+f / alt+b;
- ESC+<digit>, ESC+- and ESC+=: the characters a macOS Option key types (¡ ™ £ … – ≠), not alt+1 … alt+=;
- ESC+<punctuation> (ESC+,): the key alone (`comma`), the Alt lost.

Q3TUI's keys (Alt+F/R/V/H for the menus, Alt+1 … Alt+9 for the tabs, Alt+, for the settings) need them as Alt.
"""

from collections.abc import Callable

from textual._ansi_sequences import ANSI_SEQUENCES_KEYS
from textual._xterm_parser import XTermParser

ALIASES = ("\x1bf", "\x1bb", *(f"\x1b{c}" for c in "1234567890-="))


def enable_alt_menu_keys() -> Callable[[], None]:
    """Decode ESC+<key> as Alt+<key> for the cases above, for the app's lifetime; returns what restores Textual."""
    removed = {seq: ANSI_SEQUENCES_KEYS.pop(seq) for seq in ALIASES if seq in ANSI_SEQUENCES_KEYS}
    original = XTermParser._sequence_to_key_events

    def sequence_to_key_events(self, sequence: str, alt: bool = False):
        for event in original(self, sequence, alt):
            if alt and len(sequence) == 1 and not sequence.isalnum() and not event.key.startswith("alt+"):
                event.key = f"alt+{event.key}"  # ESC+, is alt+comma
            yield event

    XTermParser._sequence_to_key_events = sequence_to_key_events

    def restore() -> None:
        XTermParser._sequence_to_key_events = original
        for seq, keys in removed.items():
            ANSI_SEQUENCES_KEYS.setdefault(seq, keys)

    return restore
