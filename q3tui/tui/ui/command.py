"""Command: a search box over grouped commands, following shadcn's Command and CommandDialog.

Focus stays in the search box: type to filter, Down and Up move through the results, Enter runs the
highlighted one. `CommandDialog` shows it as a palette over the screen and returns the chosen value.
With `search=False` there is no box: another field filters it (`set_query`) and drives it (`move`,
`choose_highlighted`), as the slash commands of the assistant panel do.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input as TextualInput
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from q3tui.tui.ui.dialog import Dialog
from q3tui.tui.ui.icons import IconName, icon, key_label
from q3tui.tui.ui.input import Input, InputGroup, InputGroupAddon
from q3tui.tui.ui.search import fuzzy_score

__all__ = ["Command", "CommandDialog", "CommandGroup", "CommandItem"]


@dataclass
class CommandItem:
    """One command. `shortcut` is a Textual key name, drawn at the right with key icons;
    `keywords` are extra words the search also matches."""

    label: str
    value: str = ""
    shortcut: str | None = None
    icon_name: IconName | None = None
    keywords: str = ""
    disabled: bool = False
    description: str = ""  # dimmed after the label; not searched (put words in `keywords`)


class CommandGroup:
    def __init__(self, heading: str, *items: CommandItem) -> None:
        self.heading = heading
        self.items = items


class Command(Vertical):
    """`Command(CommandGroup("Session", CommandItem("New session", shortcut="ctrl+n")), ...)`.
    Posts `Command.Selected(command, item)`."""

    DEFAULT_CSS = """
    Command { height: auto; }
    Command > OptionList, Command > OptionList:focus { height: auto; max-height: 12; padding: 0;
        border: none; background: transparent; background-tint: transparent; }
    Command > OptionList > .option-list--option { padding: 0 1; }
    Command > OptionList > .option-list--option-highlighted {
        background: $primary-muted; color: $foreground; }
    """
    BINDINGS = [
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
    ]

    class Selected(Message):
        def __init__(self, command: Command, item: CommandItem) -> None:
            super().__init__()
            self.command = command
            self.item = item

        @property
        def control(self) -> Command:
            return self.command

    def __init__(
        self,
        *entries: CommandGroup | CommandItem,
        placeholder: str = "Type a command or search…",
        empty_text: str = "No results found.",
        search: bool = True,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.groups = [e if isinstance(e, CommandGroup) else CommandGroup("", e) for e in entries]
        self.placeholder = placeholder
        self.empty_text = empty_text
        self.search = search
        self.auto_highlight = True  # False: nothing is highlighted until Up or Down
        self._query = ""
        self._rows: list[CommandItem | None] = []

    @property
    def field(self) -> Input:
        return self.query_one(".command-input", Input)

    @property
    def results(self) -> OptionList:
        return self.query_one(OptionList)

    @property
    def query_text(self) -> str:
        return self.field.value if self.search else self._query

    def compose(self) -> ComposeResult:
        if self.search:
            yield InputGroup(
                InputGroupAddon("", icon_name="search"),
                Input(placeholder=self.placeholder, classes="command-input"),
            )
        yield OptionList(markup=False)

    def on_mount(self) -> None:
        if self.search:
            self.field.focus()
        else:
            self.results.can_focus = False  # the field that drives it keeps the keyboard
        self.refill()

    def set_query(self, query: str) -> None:
        """Filter by `query` (with `search=False`)."""
        self._query = query
        self.refill()

    def set_entries(self, *entries: CommandGroup | CommandItem) -> None:
        """Replace what it lists."""
        self.groups = [e if isinstance(e, CommandGroup) else CommandGroup("", e) for e in entries]
        self.refill()

    @property
    def highlighted_item(self) -> CommandItem | None:
        index = self.results.highlighted
        return self._rows[index] if index is not None and 0 <= index < len(self._rows) else None

    def choose_highlighted(self) -> None:
        self.choose(self.results.highlighted)

    def on_resize(self, event: events.Resize) -> None:
        self.refill()

    def _row(self, item: CommandItem, width: int) -> Text:
        left = f"{icon(item.icon_name)} {item.label}" if item.icon_name else item.label
        text = Text(left)
        if item.description:
            text.append(f"  {item.description}", style="dim")
            left = text.plain
        if item.shortcut and width:
            hint = key_label(item.shortcut)
            gap = max(2, width - cell_len(left) - cell_len(hint))
            text.append(" " * gap)
            text.append(hint, style="dim")
        if item.disabled:
            text.stylize("dim")
        return text

    def matches(self, query: str) -> list[tuple[CommandGroup, list[CommandItem]]]:
        found = []
        for group in self.groups:
            ranked = []
            for position, item in enumerate(group.items):
                score = fuzzy_score(query, f"{item.label} {item.keywords}".strip())
                if score is not None:
                    ranked.append((score, position, item))
            ranked.sort(key=lambda entry: entry[:2])
            if ranked:
                found.append((group, [item for _, _, item in ranked]))
        return found

    def refill(self) -> None:
        if not self.is_mounted:
            return
        width = max(0, self.results.size.width - 2)
        self._rows = []
        options: list[Option] = []
        for group, items in self.matches(self.query_text):
            if group.heading:
                options.append(Option(Text(group.heading, style="bold dim"), disabled=True))
                self._rows.append(None)
            for item in items:
                options.append(Option(self._row(item, width), disabled=item.disabled))
                self._rows.append(item)
        if not options:
            options.append(Option(Text(self.empty_text, style="dim"), disabled=True))
            self._rows.append(None)
        self.results.clear_options()
        self.results.add_options(options)
        self.results.highlighted = (
            next((n for n, row in enumerate(self._rows) if row and not row.disabled), None)
            if self.auto_highlight
            else None
        )

    @on(TextualInput.Changed)
    def _typed(self, event: TextualInput.Changed) -> None:
        event.stop()
        self.refill()

    @on(TextualInput.Submitted)
    def _submitted(self, event: TextualInput.Submitted) -> None:
        event.stop()
        index = self.results.highlighted
        self.choose(index)

    @on(OptionList.OptionSelected)
    def _clicked(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.choose(event.option_index)

    def choose(self, index: int | None) -> None:
        if index is not None and 0 <= index < len(self._rows):
            item = self._rows[index]
            if item is not None and not item.disabled:
                self.post_message(self.Selected(self, item))

    def action_move(self, direction: int) -> None:
        if direction > 0:
            self.results.action_cursor_down()
        else:
            self.results.action_cursor_up()


class CommandDialog(Dialog):
    """A `Command` over the screen. Returns the chosen item's value (or label), `None` on Escape."""

    def __init__(
        self,
        *entries: CommandGroup | CommandItem,
        placeholder: str = "Type a command or search…",
        width: int = 64,
    ) -> None:
        self.command = Command(*entries, placeholder=placeholder)
        super().__init__(self.command, show_close_button=False, width=width)

    @on(Command.Selected)
    def _selected(self, event: Command.Selected) -> None:
        event.stop()
        self.dismiss(event.item.value or event.item.label)
