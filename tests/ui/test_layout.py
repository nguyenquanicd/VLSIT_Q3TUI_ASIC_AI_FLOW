import pytest
from textual import on
from textual.widgets import Static

from q3tui.tui.ui.badge import Badge
from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.item import (
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemSeparator,
    ItemTitle,
)
from q3tui.tui.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from tests.ui.harness import Harness


class Picking(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.picked = []

    @on(Item.Selected)
    def selected(self, event):
        self.picked.append(event.value)


def row(title, value=None, **kw):
    return Item(
        ItemMedia("file"),
        ItemContent(ItemTitle(title), ItemDescription("1 MB")),
        ItemActions(Badge("New")),
        value=value,
        **kw,
    )


async def test_item_lays_out_media_content_and_actions_across_the_row():
    app = Picking(row("report.pdf", id="r"))
    async with app.run_test(size=(60, 8)) as pilot:
        await pilot.pause()
        media, content, actions = (
            app.query_one(w) for w in ("ItemMedia", "ItemContent", "ItemActions")
        )
        assert media.render().plain == icon("file")
        assert media.region.x < content.region.x < actions.region.x
        assert actions.region.right == app.query_one("#r").region.right  # No inset: the panel gives it.
        assert app.query_one(ItemTitle).region.y < app.query_one(ItemDescription).region.y


async def test_item_variants_and_a_plain_item_takes_no_focus():
    app = Picking(row("a", id="plain"), row("b", variant="muted", id="muted"))
    async with app.run_test(size=(60, 12)) as pilot:
        await pilot.pause()
        plain, muted = app.query_one("#plain"), app.query_one("#muted")
        assert not plain.can_focus
        assert muted.background_colors[1] != plain.background_colors[1]
        assert muted.region.height == plain.region.height + 2  # The half-cell edges.
    with pytest.raises(ValueError):
        Item(variant="loud")


async def test_selectable_items_post_selected_by_keys_and_click_and_arrows_move_between_them():
    group = ItemGroup(
        row("one", "one", id="one"),
        ItemSeparator(),
        row("two", "two", id="two"),
        row("three", id="three"),  # Not selectable.
        id="g",
    )
    app = Picking(group)
    async with app.run_test(size=(60, 16)) as pilot:
        app.query_one("#one").focus()
        await pilot.pause()
        await pilot.press("enter", "down")
        assert app.focused.id == "two"
        await pilot.press("space", "down")
        assert app.focused.id == "one"  # Wraps over the selectable ones only.
        await pilot.click("#two")
        await pilot.pause()
        assert app.picked == ["one", "two", "two"]


def panels(**kw):
    return ResizablePanelGroup(
        ResizablePanel(Static("left"), id="a", size=50),
        ResizableHandle(id="h"),
        ResizablePanel(Static("right"), id="b", size=50, min_size=20),
        id="g",
        **kw,
    )


async def test_resizable_handle_moves_by_arrow_shift_arrow_and_end_and_respects_min_sizes():
    app = Picking(panels())
    async with app.run_test(size=(81, 10)) as pilot:
        await pilot.pause()
        a, b, h = app.query_one("#a"), app.query_one("#b"), app.query_one("#h")
        start = a.region.width
        assert abs(a.region.width - b.region.width) <= 1 and h.region.width == 1
        h.focus()
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()
        assert a.region.width == start + 1
        await pilot.press("shift+left")
        await pilot.pause()
        assert a.region.width == start - 4
        await pilot.press("up")  # Across the group: not ours.
        await pilot.pause()
        assert a.region.width == start - 4
        await pilot.press("end")
        await pilot.pause()
        assert b.region.width >= 0.2 * 80 - 1  # The right panel keeps its minimum (20%).
        await pilot.press("home")
        await pilot.pause()
        assert a.region.width >= 0.1 * 80 - 1 and a.region.width <= 0.1 * 80 + 2


async def test_vertical_resizable_group_stacks_panels_and_moves_with_up_and_down():
    app = Picking(panels(direction="vertical"))
    async with app.run_test(size=(40, 21)) as pilot:
        await pilot.pause()
        a, b, h = app.query_one("#a"), app.query_one("#b"), app.query_one("#h")
        assert b.region.y > a.region.y and h.region.height == 1
        start = a.region.height
        h.focus()
        await pilot.pause()
        await pilot.press("down", "right")
        await pilot.pause()
        assert a.region.height == start + 1  # Right is across a vertical group.
    with pytest.raises(ValueError):
        ResizablePanelGroup(direction="diagonal")


async def test_dragging_the_handle_with_the_mouse_moves_the_divider():
    app = Picking(panels())
    async with app.run_test(size=(81, 10)) as pilot:
        await pilot.pause()
        a, h = app.query_one("#a"), app.query_one("#h")
        start = a.region.width
        await pilot.mouse_down(h)
        await pilot.hover(offset=(h.region.x + 10, 3))
        await pilot.mouse_up(offset=(h.region.x + 10, 3))
        await pilot.pause()
        assert a.region.width > start + 5


async def test_resizable_ignores_a_hidden_panel_when_moving_the_handle():
    app = Picking(panels())
    async with app.run_test(size=(81, 10)) as pilot:
        await pilot.pause()
        a, b, h = app.query_one("#a"), app.query_one("#b"), app.query_one("#h")
        b.display = False
        h.display = False
        await pilot.pause()
        assert app.query_one("#g", ResizablePanelGroup).visible_panels == [a]
