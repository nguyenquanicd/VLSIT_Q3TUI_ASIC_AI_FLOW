import pytest

from q3tui.tui.ui.alert_dialog import AlertDialog
from q3tui.tui.ui.dialog import Dialog, DialogClose, DialogContent, DialogTitle
from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.input import Input
from q3tui.tui.ui.sheet import Sheet, SheetDescription, SheetFooter, SheetHeader, SheetTitle
from tests.ui.harness import Harness


class Opener(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.results = []

    def open(self, screen):
        self.push_screen(screen, self.results.append)


async def test_alert_dialog_returns_true_for_the_action_and_false_for_cancel():
    app = Opener(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open(AlertDialog("Save changes?", "Your edits will be kept.", action="Save"))
        await pilot.pause()
        assert isinstance(app.screen, Dialog) and not app.screen.query(".dialog-close")
        assert app.focused.id == "alert-action"
        action = app.screen.query_one("#alert-action", DialogClose)
        assert action.label.plain == f"{icon('key_enter')} Save"
        await pilot.press("enter")
        await pilot.pause()
        app.open(AlertDialog("Save changes?"))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.results == [True, False]


async def test_alert_dialog_ignores_clicks_outside_and_is_not_dismissed_by_them():
    app = Opener(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open(AlertDialog("Sure?"))
        await pilot.pause()
        await pilot.click(offset=(1, 1))
        await pilot.pause()
        assert isinstance(app.screen, Dialog) and app.results == []


async def test_destructive_alert_dialog_starts_on_cancel_and_confirms_with_y_not_enter():
    app = Opener(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open(
            AlertDialog(
                "Delete session", "This cannot be undone.", action="Delete", destructive=True
            )
        )
        await pilot.pause()
        assert app.focused.id == "alert-cancel"
        action = app.screen.query_one("#alert-action", DialogClose)
        assert action.label.plain == "Y Delete"  # A dialog button shows its key before the label.
        await pilot.press("enter")  # Presses the focused Cancel, not the destructive action.
        await pilot.pause()
        app.open(AlertDialog("Delete session", action="Delete", destructive=True))
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.results == [False, True]


async def test_alert_dialog_takes_a_custom_action_key():
    app = Opener(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open(AlertDialog("Quit?", action="Quit", action_key="ctrl+g"))
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app.results == [True]


@pytest.mark.parametrize("side", ["right", "left", "top", "bottom"])
async def test_sheet_docks_to_its_edge_and_fills_the_other_axis(side):
    sheet = Sheet(
        SheetHeader(SheetTitle("Settings"), SheetDescription("Tune it.")), side=side, size=20
    )
    app = Opener(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open(sheet)
        await pilot.pause()
        box = sheet.query_one(DialogContent)
        if side == "right":
            assert box.region.right == 80 and box.region.width == 20 and box.region.height == 24
        elif side == "left":
            assert box.region.x == 0 and box.region.width == 20 and box.region.height == 24
        elif side == "top":
            assert box.region.y == 0 and box.region.height == 20 and box.region.width == 80
        else:
            assert box.region.bottom == 24 and box.region.height == 20 and box.region.width == 80
        assert sheet.query_one(DialogTitle).render().plain == "Settings"
        await pilot.press("escape")
        await pilot.pause()
        assert app.results == [None]


async def test_sheet_returns_a_close_value_and_rejects_a_bad_side():
    sheet = Sheet(SheetFooter(DialogClose("Save", "saved", key="enter", id="s")))
    app = Opener(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open(sheet)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.results == ["saved"]
    with pytest.raises(ValueError):
        Sheet(side="middle")


# -- Popover --------------------------------------------------------------------------------------

from q3tui.tui.ui.button import Button
from q3tui.tui.ui.context_menu import ContextMenu
from q3tui.tui.ui.menu import (
    MenuContent,
    MenuItem,
    MenuLabel,
    MenuSeparator,
    MenuSub,
    MenuSubContent,
    MenuSubTrigger,
)
from q3tui.tui.ui.popover import Popover, PopoverContent, PopoverTrigger
from q3tui.tui.ui.toast import Toast, Toaster, toast


def make_popover(**kw):
    return Popover(
        PopoverTrigger("Dimensions", key="f4", id="trig"),
        Input(id="width"),
        Button("Apply", id="apply"),
        id="pop",
        **kw,
    )


async def test_popover_opens_below_the_trigger_and_focuses_its_first_field():
    app = Harness(make_popover(), Input(id="elsewhere"))
    async with app.run_test(size=(60, 20)) as pilot:
        pop = app.query_one("#pop", Popover)
        app.query_one("#trig").focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        box = pop.content
        assert pop.is_open and isinstance(box, PopoverContent)
        assert box.region.y == pop.trigger.region.bottom and box.region.x == pop.trigger.region.x
        assert app.focused.id == "width"  # Focus moved into the popover.
        assert pop.trigger.has_class("-open")
        await pilot.press("tab")
        assert app.focused.id == "apply"  # Tab stays inside while it is open.
        await pilot.press("escape")
        await pilot.pause()
        assert not pop.is_open and app.focused is pop.trigger and not pop.trigger.has_class("-open")


async def test_popover_closes_on_outside_click_and_when_focus_leaves_and_toggles_by_key():
    app = Harness(make_popover(), Input(id="elsewhere"))
    async with app.run_test(size=(60, 20)) as pilot:
        pop = app.query_one("#pop", Popover)
        await pilot.press("f4")
        await pilot.pause()
        assert pop.is_open
        await pilot.press("f4")
        await pilot.pause()
        assert not pop.is_open
        await pop.open()
        await pilot.pause()
        await pilot.click("#elsewhere", offset=(50, 1))  # Away from the popup, which covers x < 20.
        await pilot.pause()
        assert not pop.is_open
        await pop.open()
        await pilot.pause()
        app.query_one("#elsewhere").focus()
        await pilot.pause(0.05)  # Closing is scheduled after the next refresh.
        assert not pop.is_open


async def test_popover_aligns_to_the_end_flips_above_near_the_bottom_and_stays_on_screen():
    app = Harness(make_popover(align="end"))
    async with app.run_test(size=(60, 20)) as pilot:
        pop = app.query_one("#pop", Popover)
        await pop.open()
        await pilot.pause()
        box = pop.content
        assert box.region.right == pop.trigger.region.right or box.region.x == 0
    app = Harness(Input(id="pad"), make_popover(side="top"))
    app.CSS = "#pad { height: 3; } #pop { margin-top: 4; }"
    async with app.run_test(size=(60, 20)) as pilot:
        pop = app.query_one("#pop", Popover)
        await pop.open()
        await pilot.pause()
        box = pop.content
        assert box.region.bottom <= pop.trigger.region.y  # Above the trigger.
        assert box.region.y >= 0


# -- Context menu ---------------------------------------------------------------------------------


def make_context(**kw):
    return ContextMenu(
        MenuContent(
            MenuLabel("Edit"),
            MenuItem("Copy", "copy"),
            MenuItem("Paste", "paste", disabled=True),
            MenuSeparator(),
            MenuSub(MenuSubTrigger("More"), MenuSubContent(MenuItem("Select all", "all"))),
        ),
        Input(id="field"),
        id="ctx",
        **kw,
    )


class Selecting(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.picked = []

    def on_context_menu_selected(self, event):
        self.picked.append(event.value)


async def test_context_menu_opens_at_the_pointer_on_right_click_and_selects():
    from textual.events import MouseDown

    app = Selecting(make_context())
    async with app.run_test(size=(60, 20)) as pilot:
        menu = app.query_one("#ctx", ContextMenu)
        field = app.query_one("#field")
        await pilot.click(field, offset=(5, 1), button=3)
        await pilot.pause()
        popup = menu.active_popup
        assert popup is not None
        assert popup.region.y == field.region.y + 1 and popup.region.x == field.region.x + 5
        await pilot.press("enter")
        await pilot.pause()
        assert app.picked == ["copy"] and menu.active_popup is None
        assert MouseDown  # Right button is 3.


async def test_context_menu_opens_with_shift_f10_below_the_focused_widget_and_returns_focus():
    app = Selecting(make_context())
    async with app.run_test(size=(60, 20)) as pilot:
        menu = app.query_one("#ctx", ContextMenu)
        field = app.query_one("#field")
        field.focus()
        await pilot.pause()
        await pilot.press("shift+f10")
        await pilot.pause()
        popup = menu.active_popup
        assert popup is not None and popup.region.y == field.region.bottom
        assert popup.region.x == field.region.x
        await pilot.press("down", "right")  # "More" -> its submenu.
        assert len(menu.popups) == 2
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert menu.active_popup is None and app.focused is field
        assert not app.screen.query("_Anchor")  # The anchor is gone with the menu.


async def test_a_left_click_does_not_open_the_context_menu():
    app = Selecting(make_context())
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.click("#field")
        await pilot.pause()
        assert app.query_one("#ctx", ContextMenu).active_popup is None


# -- Toast ----------------------------------------------------------------------------------------


async def test_toast_appears_bottom_right_stacks_and_goes_away_by_itself():
    app = Harness(Input(id="x"))
    async with app.run_test(size=(80, 24)) as pilot:
        item = await toast(app.screen, "Saved", "Safe.", variant="success", duration=0.3)
        await pilot.pause()
        toaster = app.screen.query_one(Toaster)
        await pilot.pause(0.1)
        assert isinstance(item, Toast) and item.has_class("-success")
        assert item.region.right <= 80 and item.region.bottom <= 24
        assert item.region.right >= 80 - 2  # In the corner.
        second = await toast(app.screen, "Second", duration=5)
        await pilot.pause()
        assert second.region.y > item.region.y  # Newest at the bottom.
        await pilot.pause(0.6)
        assert not item.is_attached and second.is_attached
        assert len(toaster.query(Toast)) == 1


async def test_toaster_keeps_at_most_three_and_can_be_cleared():
    app = Harness(Input(id="x"))
    async with app.run_test(size=(80, 30)) as pilot:
        for n in range(5):
            await toast(app.screen, f"Toast {n}", duration=0)
        await pilot.pause()
        toaster = app.screen.query_one(Toaster)
        titles = [t.query_one("AlertTitle").render().plain for t in toaster.query(Toast)]
        assert titles == ["Toast 2", "Toast 3", "Toast 4"]
        await toaster.clear()
        await pilot.pause()
        assert not toaster.query(Toast) and not toaster.display


