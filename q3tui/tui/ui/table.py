"""Table and DataTable, following shadcn's Table and Data Table."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable as TextualDataTable
from textual.widgets import Static

__all__ = ["DataTable", "Table"]

Align = Literal["left", "right", "center"]


def _pad(text: str, width: int, align: Align) -> str:
    gap = width - cell_len(text)
    if align == "right":
        return " " * gap + text
    if align == "center":
        return " " * (gap // 2) + text + " " * (gap - gap // 2)
    return text + " " * gap


class Table(Vertical):
    """A static table: a header, rows, an optional footer row, and an optional caption.

    `Table(["Name", "Qty"], [["Apple", 3]], align=["left", "right"], footer=["Total", 3])`.
    Columns are as wide as their widest cell, two cells apart; there is no wrapping, scrolling, or
    selection (use `DataTable` for those).
    """

    DEFAULT_CSS = """
    Table { width: auto; height: auto; }
    Table > Static { width: auto; }
    Table > .table-head { background: $panel; text-style: bold; padding: 0 1; }
    Table > .table-row { padding: 0 1; }
    Table > .table-foot { text-style: bold; padding: 0 1; border-top: solid $border-blurred; }
    Table > .table-caption { color: $text-muted; padding: 0 1; }
    """

    def __init__(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[object]],
        *,
        align: Sequence[Align] | None = None,
        footer: Sequence[object] | None = None,
        caption: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.columns = list(columns)
        self.rows = [[str(cell) for cell in row] for row in rows]
        self.footer = [str(cell) for cell in footer] if footer is not None else None
        self.align: list[Align] = list(align) if align else ["left"] * len(self.columns)
        self.caption = caption

    def widths(self) -> list[int]:
        every = [self.columns, *self.rows, *([self.footer] if self.footer else [])]
        return [
            max(cell_len(row[i]) for row in every if i < len(row)) for i in range(len(self.columns))
        ]

    def line(self, row: Sequence[str]) -> str:
        widths = self.widths()
        cells = [
            _pad(row[i] if i < len(row) else "", widths[i], self.align[i])
            for i in range(len(widths))
        ]
        return "  ".join(cells)

    def compose(self) -> ComposeResult:
        yield Static(Text(self.line(self.columns)), classes="table-head")
        for row in self.rows:
            yield Static(Text(self.line(row)), classes="table-row")
        if self.footer is not None:
            yield Static(Text(self.line(self.footer)), classes="table-foot")
        if self.caption:
            yield Static(self.caption, classes="table-caption", markup=False)


class DataTable(TextualDataTable):
    """Textual's `DataTable` with the project look: row cursor, a bold header, a `$primary-muted`
    cursor row. Arrow keys move, Enter posts Textual's `DataTable.RowSelected`."""

    DEFAULT_CSS = """
    DataTable { height: auto; max-height: 20; background: transparent; border: none; padding: 0;
        color: $foreground; }
    DataTable:focus { border: none; background-tint: transparent; }
    DataTable > .datatable--header { background: $panel; text-style: bold; color: $foreground; }
    DataTable > .datatable--cursor { background: $primary-muted; color: $foreground; }
    DataTable > .datatable--hover { background: $panel; }
    """

    def __init__(
        self,
        columns: Sequence[str] = (),
        rows: Sequence[Sequence[object]] = (),
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(cursor_type="row", zebra_stripes=False, id=id, classes=classes)
        self._initial = (list(columns), [list(row) for row in rows])

    def on_mount(self) -> None:
        self.load(*self._initial)

    def load(self, columns: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
        """Replace the whole table."""
        self.clear(columns=True)
        self.add_columns(*columns)
        for row in rows:
            self.add_row(*row)
