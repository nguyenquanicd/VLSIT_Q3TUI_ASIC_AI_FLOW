import pytest
from rich.cells import cell_len
from textual import on

from q3tui.tui.ui.combobox import Combobox, ComboboxItem
from q3tui.tui.ui.command import Command, CommandDialog, CommandGroup, CommandItem
from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.input import Input
from q3tui.tui.ui.select import Select, SelectGroup, SelectItem, SelectSeparator
from tests.ui.harness import Harness


class Recorder(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.events = []

    @on(Select.Changed)
    def select_changed(self, event):
        self.events.append(("select", event.select.id, event.value, event.label))


def fruit_select(**kw):
    return Select(
        SelectItem("Apple", "apple"),
        SelectItem("Banana", "banana", disabled=True),
        SelectSeparator(),
        SelectGroup("Veg", SelectItem("Carrot", "carrot"), SelectItem("Leek", "leek")),
        id="s",
        **kw,
    )


async def test_select_shows_the_placeholder_then_the_chosen_label_with_a_chevron_at_the_right():
    app = Recorder(fruit_select(placeholder="Pick one"))
    async with app.run_test(size=(40, 14)) as pilot:
        await pilot.pause()
        select = app.query_one("#s", Select)
        trigger = select.trigger
        assert select.value is None
        text = trigger.render().plain
        assert text.startswith("Pick one") and text.endswith(icon("chevron_down"))
        assert trigger.region.height == 3 and trigger.region.width == 40
        assert len(text) == trigger.region.width - 2  # The chevron sits at the right edge.
        await select.open()
        await pilot.press("enter")
        await pilot.pause()
        assert select.value == "apple"
        assert trigger.render().plain.startswith("Apple")
        assert app.events == [("select", "s", "apple", "Apple")]
        assert select.active_popup is None  # Choosing closes the menu.


async def test_select_popup_is_as_wide_as_the_trigger_and_lists_groups_and_disabled_items():
    app = Recorder(fruit_select(width=30))
    async with app.run_test(size=(60, 14)) as pilot:
        select = app.query_one("#s", Select)
        select.focus()
        await pilot.pause()
        await pilot.press("down")
        popup = select.active_popup
        assert popup.region.width == select.trigger.region.width == 30
        assert popup.region.x == select.trigger.region.x
        labels = [
            getattr(r.item, "label", None) or getattr(r.item, "text", None) for r in popup.rows
        ]
        assert labels == ["Apple", "Banana", "Veg", "Carrot", "Leek"]
        assert popup.rows[1].item.disabled
        await pilot.press("down")  # Skips disabled Banana.
        assert popup.rows[popup.highlighted].item.label == "Carrot"
        await pilot.press("l", "enter")  # Typeahead.
        await pilot.pause()
        assert select.value == "leek"


async def test_select_marks_the_current_value_and_keeps_it_when_dismissed():
    app = Recorder(fruit_select(value="carrot"))
    async with app.run_test(size=(40, 14)) as pilot:
        select = app.query_one("#s", Select)
        assert select.trigger.render().plain.startswith("Carrot")
        await select.open()
        await pilot.pause()
        row = next(r for r in select.active_popup.rows if getattr(r.item, "value", "") == "carrot")
        assert row.group.value == "carrot"
        await pilot.press("escape")
        assert select.value == "carrot" and app.events == []


async def test_set_value_changes_the_display_notifies_and_rejects_unknown_values():
    app = Recorder(fruit_select())
    async with app.run_test(size=(40, 14)) as pilot:
        select = app.query_one("#s", Select)
        select.set_value("leek")
        await pilot.pause()
        assert select.trigger.render().plain.startswith("Leek")
        assert app.events == [("select", "s", "leek", "Leek")]
        select.set_value(None, notify=False)
        await pilot.pause()
        assert select.trigger.render().plain.startswith("Select an option")
        assert len(app.events) == 1
        with pytest.raises(ValueError):
            select.set_value("nope")


async def test_a_select_changed_message_does_not_leak_as_a_dropdown_selection():
    from q3tui.tui.ui.dropdown_menu import DropdownMenu

    class Leak(Recorder):
        leaked = 0

        @on(DropdownMenu.Selected)
        def leak(self, event):
            Leak.leaked += 1

    app = Leak(fruit_select())
    async with app.run_test(size=(40, 14)) as pilot:
        await app.query_one("#s", Select).open()
        await pilot.press("enter")
        await pilot.pause()
        assert Leak.leaked == 0 and len(app.events) == 1


def test_fuzzy_score_prefers_prefixes_then_runs_then_scattered_letters():
    from q3tui.tui.ui.search import fuzzy_score

    assert fuzzy_score("", "anything") == 0
    assert fuzzy_score("app", "Apple") == 0
    assert fuzzy_score("ple", "Apple") == 2
    assert 100 <= fuzzy_score("ae", "Apple") < 200  # Scattered, in order.
    assert fuzzy_score("ea", "Apple") is None  # Wrong order.
    assert fuzzy_score("z", "Apple") is None
    assert fuzzy_score("APP", "apple") == 0  # Case does not matter.


def combo(**kw):
    return Combobox(
        ComboboxItem("Apple", "apple"),
        ComboboxItem("Apricot", "apricot", disabled=True),
        "Banana",
        "Blueberry",
        id="c",
        **kw,
    )


def option_texts(popup):
    return [str(popup.get_option_at_index(i).prompt) for i in range(popup.option_count)]


class ComboRecorder(Recorder):
    @on(Combobox.Chosen)
    def chosen(self, event):
        self.events.append(("chosen", event.combobox.id, event.value, event.label))


async def test_combobox_filters_as_you_type_and_chooses_with_enter():
    app = ComboRecorder(combo())
    async with app.run_test(size=(40, 16)) as pilot:
        box = app.query_one("#c", Combobox)
        box.focus()
        await pilot.pause()
        assert not box.is_open
        await pilot.press("b")
        await pilot.pause()
        assert box.is_open
        assert option_texts(box._popup)[:2] == ["Banana", "Blueberry"]  # Prefix matches first.
        await pilot.press("down", "enter")
        await pilot.pause()
        assert box.value == "Blueberry" and box.choice == "Blueberry"
        assert not box.is_open
        assert app.events == [("chosen", "c", "Blueberry", "Blueberry")]


async def test_combobox_opens_with_down_skips_disabled_closes_with_escape_and_on_blur():
    app = ComboRecorder(combo(), Input(id="other"))
    async with app.run_test(size=(40, 16)) as pilot:
        box = app.query_one("#c", Combobox)
        box.focus()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        popup = box._popup
        assert box.is_open and popup.region.width == box.region.width
        assert popup.region.y == box.region.bottom and popup.region.x == box.region.x
        assert popup.highlighted == 0  # "Apple"; "Apricot" is disabled.
        await pilot.press("down")
        assert popup.highlighted == 2  # Skips the disabled row.
        await pilot.press("escape")
        await pilot.pause()
        assert not box.is_open
        await pilot.press("down")
        await pilot.pause()
        assert box.is_open
        app.query_one("#other").focus()
        await pilot.pause()
        assert not box.is_open


async def test_combobox_shows_the_empty_text_and_a_click_chooses_an_item():
    app = ComboRecorder(combo(empty_text="Nothing here"))
    async with app.run_test(size=(40, 16)) as pilot:
        box = app.query_one("#c", Combobox)
        box.focus()
        await pilot.pause()
        await pilot.press("z", "z")
        await pilot.pause()
        popup = box._popup
        assert option_texts(popup) == ["Nothing here"] and popup.get_option_at_index(0).disabled
        await pilot.press("enter")  # Nothing to choose.
        assert box.is_open and app.events == []
        await pilot.press("backspace", "backspace", "b")
        await pilot.pause()
        await pilot.click(box._popup, offset=(3, 1))  # Row 0 is the top edge.
        await pilot.pause()
        assert box.choice == "Banana" and app.events == [("chosen", "c", "Banana", "Banana")]


async def test_combobox_set_value_and_unknown_values():
    app = ComboRecorder(combo(value="apple"))
    async with app.run_test(size=(40, 16)) as pilot:
        box = app.query_one("#c", Combobox)
        await pilot.pause()
        assert box.value == "Apple" and box.choice == "apple" and app.events == []
        box.set_value("Banana")
        await pilot.pause()
        assert box.value == "Banana" and app.events[-1][2] == "Banana"
        with pytest.raises(ValueError):
            box.set_value("nope")


def palette(**kw):
    return Command(
        CommandGroup(
            "Session",
            CommandItem("New session", "new", shortcut="ctrl+n", icon_name="new_session"),
            CommandItem("Clear prompt", "clear", keywords="reset empty"),
        ),
        CommandGroup(
            "Settings",
            CommandItem("Theme: Dark", "dark"),
            CommandItem("Theme: Light", "light", disabled=True),
            CommandItem("Quit", "quit", shortcut="ctrl+q"),
        ),
        id="cmd",
        **kw,
    )


class CommandRecorder(Recorder):
    @on(Command.Selected)
    def selected(self, event):
        self.events.append(("command", event.item.value))


def rows(command):
    return [None if r is None else r.value for r in command._rows]


async def test_command_lists_groups_with_shortcuts_and_highlights_the_first_command():
    app = CommandRecorder(palette())
    async with app.run_test(size=(50, 20)) as pilot:
        command = app.query_one("#cmd", Command)
        await pilot.pause()
        assert rows(command) == [None, "new", "clear", None, "dark", "light", "quit"]
        assert command.results.highlighted == 1  # The first row is a heading.
        assert app.focused is command.field
        first = str(command.results.get_option_at_index(1).prompt)
        assert first.startswith(f"{icon('new_session')} New session")
        assert first.endswith(key_label("ctrl+n"))  # The shortcut sits at the right edge.
        assert cell_len(first) == command.results.size.width - 2


async def test_command_filters_by_label_and_keywords_and_hides_empty_groups():
    app = CommandRecorder(palette())
    async with app.run_test(size=(50, 20)) as pilot:
        command = app.query_one("#cmd", Command)
        await pilot.press("t", "h", "e")
        await pilot.pause()
        assert rows(command) == [None, "dark", "light"]  # Only "Settings" is left.
        command.field.clear()
        await pilot.press(*"reset")
        await pilot.pause()
        assert rows(command) == [None, "clear"]  # Found through its keywords.
        await pilot.press(*"zzz")
        await pilot.pause()
        assert rows(command) == [None]
        assert str(command.results.get_option_at_index(0).prompt) == "No results found."
        assert command.results.highlighted is None


async def test_command_runs_the_highlighted_item_on_enter_and_skips_disabled_ones():
    app = CommandRecorder(palette())
    async with app.run_test(size=(50, 20)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        assert app.events == [("command", "new")]
        await pilot.press("down", "down", "down")  # New, Clear, Dark, then Quit: Light is disabled.
        await pilot.press("enter")
        assert app.events[-1] == ("command", "quit")
        await pilot.press("up", "up", "up")  # Back to New.
        await pilot.press("enter")
        assert app.events[-1] == ("command", "new")


async def test_a_click_runs_a_command():
    app = CommandRecorder(palette())
    async with app.run_test(size=(50, 20)) as pilot:
        command = app.query_one("#cmd", Command)
        await pilot.pause()
        await pilot.click(command.results, offset=(5, 2))  # Row 2: "Clear prompt".
        assert app.events == [("command", "clear")]


async def test_command_dialog_returns_the_value_and_none_on_escape():
    class Opener(Harness):
        results: list = []

    app = Opener(Input(id="x"))
    Opener.results = []
    async with app.run_test(size=(80, 30)) as pilot:
        app.push_screen(CommandDialog(*palette().groups), Opener.results.append)
        await pilot.pause()
        assert app.focused.has_class("command-input")  # Ready to type.
        await pilot.press("c", "l", "enter")
        await pilot.pause()
        assert Opener.results == ["clear"]
        app.push_screen(CommandDialog(*palette().groups), Opener.results.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert Opener.results == ["clear", None]


# -- Calendar and DatePicker ----------------------------------------------------------------------

from datetime import date

from q3tui.tui.ui.date_picker import Calendar, DatePicker


class Dating(Recorder):
    @on(Calendar.Selected)
    def day(self, event):
        self.events.append(("day", event.value))

    @on(DatePicker.Changed)
    def picked(self, event):
        self.events.append(("picked", event.value))


async def test_calendar_draws_the_month_with_weekday_names_and_marks_the_chosen_day():
    from tests.ui.harness import screen_text

    app = Dating(Calendar(date(2026, 10, 14), id="c"))
    async with app.run_test(size=(40, 14)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "October 2026" in text and "Mo Tu We Th Fr Sa Su" in text
        assert " 1  2  3  4" in text or "1  2  3" in text
        assert "31" in text  # The last day of October.
        cal = app.query_one("#c", Calendar)
        assert cal.value == date(2026, 10, 14) and cal.cursor == date(2026, 10, 14)


async def test_calendar_keys_move_the_cursor_change_months_and_pick_a_day():
    app = Dating(Calendar(date(2026, 10, 14), id="c"))
    async with app.run_test(size=(40, 14)) as pilot:
        cal = app.query_one("#c", Calendar)
        cal.focus()
        await pilot.pause()
        await pilot.press("right")
        assert cal.cursor == date(2026, 10, 15)
        await pilot.press("down", "up", "up")
        assert cal.cursor == date(2026, 10, 8)
        await pilot.press("home")  # Monday of that week.
        assert cal.cursor == date(2026, 10, 5)
        await pilot.press("end")
        assert cal.cursor == date(2026, 10, 11)
        await pilot.press("pagedown")
        assert cal.cursor == date(2026, 11, 11)
        await pilot.press("shift+pageup")
        assert cal.cursor == date(2025, 11, 11)
        await pilot.press("enter")
        await pilot.pause()
        assert cal.value == date(2025, 11, 11) and app.events == [("day", date(2025, 11, 11))]
        await pilot.press("t")
        assert cal.cursor == date.today()


async def test_calendar_clamps_months_and_respects_minimum_and_maximum():
    app = Dating(
        Calendar(date(2026, 1, 31), minimum=date(2026, 1, 10), maximum=date(2026, 3, 15), id="c")
    )
    async with app.run_test(size=(40, 14)) as pilot:
        cal = app.query_one("#c", Calendar)
        cal.focus()
        await pilot.pause()
        await pilot.press("pagedown")
        assert cal.cursor == date(2026, 2, 28)  # January 31 + 1 month: the month is shorter.
        await pilot.press("pagedown", "pagedown")
        assert cal.cursor <= date(2026, 3, 15)
        for _ in range(120):
            await pilot.press("left")
        assert cal.cursor == date(2026, 1, 10)  # Cannot go before the minimum.
        cal.pick(date(2026, 1, 1))  # Outside the range: ignored.
        assert cal.value == date(2026, 1, 31)


async def test_clicking_a_day_picks_it_and_the_header_arrows_change_the_month():
    from tests.ui.harness import screen_text

    app = Dating(Calendar(date(2026, 10, 14), id="c"))
    async with app.run_test(size=(40, 14)) as pilot:
        cal = app.query_one("#c", Calendar)
        await pilot.pause()
        await pilot.click(cal, offset=(1 + 7 * 3 - 2, 0))  # The right arrow in the header.
        await pilot.pause()
        assert cal.cursor.month == 11 and "November 2026" in screen_text(app)
        await pilot.click(cal, offset=(1, 0))
        await pilot.pause()
        assert cal.cursor.month == 10
        strips = screen_text(app).splitlines()
        row = next(n for n, line in enumerate(strips) if "Mo Tu We" in line)
        # October 2026 starts on a Thursday: the first week has the 1st in the fourth column.
        await pilot.click(offset=(1 + 1 + 3 * 3, row + 1))
        await pilot.pause()
        assert app.events == [("day", date(2026, 10, 1))]


async def test_date_picker_opens_a_calendar_and_shows_the_picked_date():
    app = Dating(DatePicker(date(2026, 10, 14), key="f4", id="d"))
    async with app.run_test(size=(60, 20)) as pilot:
        picker = app.query_one("#d", DatePicker)
        await pilot.pause()
        assert "2026-10-14" in picker.trigger.render().plain
        await pilot.press("f4")
        await pilot.pause()
        assert picker.is_open and app.focused.__class__ is Calendar  # Focus is on the grid.
        await pilot.press("right", "enter")
        await pilot.pause(0.1)
        assert picker.value == date(2026, 10, 15) and not picker.is_open
        assert "2026-10-15" in picker.trigger.render().plain
        assert sorted(app.events) == [("day", date(2026, 10, 15)), ("picked", date(2026, 10, 15))]
        await pilot.press("f4")  # It opens again, on the new date.
        await pilot.pause()
        assert picker.is_open and app.query_one(Calendar).cursor == date(2026, 10, 15)


async def test_an_empty_date_picker_shows_its_placeholder():
    app = Dating(DatePicker(placeholder="Due date", id="d"))
    async with app.run_test(size=(60, 10)) as pilot:
        await pilot.pause()
        assert "Due date" in app.query_one("#d", DatePicker).trigger.render().plain
