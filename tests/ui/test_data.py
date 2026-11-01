from textual import on
from textual.widgets import DataTable as TextualDataTable

from q3tui.tui.ui.table import DataTable, Table
from tests.ui.harness import Harness


async def test_table_aligns_columns_and_shows_header_footer_and_caption():
    table = Table(
        ["Item", "Qty"],
        [["Apple", 3], ["Watermelon", 12]],
        align=["left", "right"],
        footer=["Total", 15],
        caption="Fruit on hand",
        id="t",
    )
    app = Harness(table)
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        assert table.widths() == [10, 3]
        head = table.query_one(".table-head").render().plain
        rows = [r.render().plain for r in table.query(".table-row")]
        foot = table.query_one(".table-foot").render().plain
        assert head == "Item        Qty"  # Two cells between columns.
        assert rows == ["Apple         3", "Watermelon   12"]
        assert foot == "Total        15"
        assert len({len(head), *map(len, rows), len(foot)}) == 1  # Every line is the same width.
        assert table.query_one(".table-caption").render().plain == "Fruit on hand"
        assert table.region.width == len(head) + 2  # One cell of padding each side.


async def test_table_without_a_footer_or_caption_has_only_header_and_rows():
    table = Table(["A"], [["x"]], id="t")
    app = Harness(table)
    async with app.run_test(size=(20, 8)) as pilot:
        await pilot.pause()
        assert not table.query(".table-foot") and not table.query(".table-caption")
        assert table.region.height == 2


class DataRecorder(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.rows = []

    @on(TextualDataTable.RowSelected)
    def selected(self, event):
        self.rows.append(event.data_table.get_row_at(event.cursor_row))


async def test_data_table_moves_a_row_cursor_and_enter_selects_the_row():
    table = DataTable(
        ["Name", "Role"], [["Ada", "Math"], ["Grace", "Navy"], ["Linus", "Kernel"]], id="d"
    )
    app = DataRecorder(table)
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        assert table.cursor_type == "row" and table.row_count == 3
        table.focus()
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert app.rows == [["Linus", "Kernel"]]
        await pilot.press("up", "enter")
        assert app.rows[-1] == ["Grace", "Navy"]


async def test_data_table_load_replaces_everything_and_has_no_border():
    table = DataTable(["A"], [["1"]], id="d")
    app = DataRecorder(table)
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        table.load(["X", "Y"], [["a", "b"], ["c", "d"]])
        await pilot.pause()
        assert [str(c.label) for c in table.columns.values()] == ["X", "Y"]
        assert table.row_count == 2
        assert table.styles.border_top[0] == ""
