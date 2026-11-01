import pytest
from textual import on

from q3tui.tui.ui.button import Button, ButtonGroup, Toggle, ToggleGroup
from q3tui.tui.ui.icons import icon, key_label
from tests.ui.harness import Harness


class Recorder(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.events = []

    @on(Button.Pressed)
    def pressed(self, event):
        self.events.append(("pressed", event.button.id))

    @on(Toggle.Changed)
    def toggled(self, event):
        self.events.append(("toggle", event.toggle.id, event.pressed))

    @on(ToggleGroup.Changed)
    def grouped(self, event):
        self.events.append(("group", event.group.id, event.value))


async def test_button_is_one_row_with_text_padding_and_the_key_hint_after_the_label():
    app = Recorder(Button("Save", key="ctrl+s", icon_name="about", id="b"))
    async with app.run_test(size=(50, 6)) as pilot:
        await pilot.pause()
        button = app.query_one("#b", Button)
        text = f"{icon('about')} Save {key_label('ctrl+s')}"
        assert button.render().plain == text
        assert button.region.height == 1
        assert button.region.width == len(text) + 2  # One cell of padding on each side.


@pytest.mark.parametrize("variant", ["secondary", "destructive", "outline", "ghost", "link"])
async def test_button_variants_look_different_from_the_default(variant):
    app = Recorder(Button("A", id="d"), Button("A", variant=variant, id="v"))
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        default, other = app.query_one("#d"), app.query_one("#v")
        assert (other.background_colors[1], other.styles.color) != (
            default.background_colors[1],
            default.styles.color,
        ) or other.styles.text_style != default.styles.text_style


async def test_enter_space_and_click_press_a_focused_button_but_not_a_disabled_one():
    app = Recorder(Button("One", id="one"), Button("Two", id="two", disabled=True))
    async with app.run_test(size=(50, 6)) as pilot:
        app.query_one("#one").focus()
        await pilot.press("enter", "space")
        await pilot.click("#one")
        await pilot.click("#two")
        await pilot.pause()
        assert app.events == [("pressed", "one")] * 3


async def test_a_key_presses_the_button_from_anywhere_on_the_screen_until_it_unmounts():
    app = Recorder(Button("Save", key="ctrl+s", id="save"), Button("Other", id="other"))
    async with app.run_test(size=(50, 6)) as pilot:
        app.query_one("#other").focus()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.events == [("pressed", "save")]
        await app.query_one("#save").remove()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.events == [("pressed", "save")]  # The binding left with the button.


async def test_a_focused_button_keeps_its_own_enter_over_another_buttons_enter_key():
    app = Recorder(Button("Go", key="enter", id="go"), Button("Cancel", id="cancel"))
    async with app.run_test(size=(50, 6)) as pilot:
        app.query_one("#cancel").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.events == [("pressed", "cancel")]


async def test_a_loading_button_shows_a_spinner_and_ignores_presses():
    app = Recorder(Button("Saving", loading=True, id="b"))
    async with app.run_test(size=(50, 6)) as pilot:
        button = app.query_one("#b", Button)
        spinners = {icon(f"spinner_{i}") for i in range(1, 7)}
        assert button.render().plain[0] in spinners
        button.focus()
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.events == []
        button.set_loading(False)
        await pilot.press("enter")
        await pilot.pause()
        assert app.events == [("pressed", "b")]


async def test_button_group_moves_focus_along_it_and_skips_disabled_buttons():
    group = ButtonGroup(
        Button("A", id="a"), Button("B", id="b", disabled=True), Button("C", id="c"), id="g"
    )
    app = Recorder(group)
    async with app.run_test(size=(50, 6)) as pilot:
        app.query_one("#a").focus()
        await pilot.press("right")
        assert app.focused.id == "c"
        await pilot.press("right")
        assert app.focused.id == "a"  # Wraps.
        await pilot.press("left")
        assert app.focused.id == "c"
        await pilot.press("down")  # Not this group's axis.
        assert app.focused.id == "c"
        a = app.query_one("#a")
        assert app.query_one("#b").region.x == a.region.right + 1


async def test_vertical_button_group_uses_up_and_down():
    app = Recorder(ButtonGroup(Button("A", id="a"), Button("B", id="b"), orientation="vertical"))
    async with app.run_test(size=(50, 8)) as pilot:
        app.query_one("#a").focus()
        await pilot.press("down")
        assert app.focused.id == "b"
        await pilot.press("right")
        assert app.focused.id == "b"
        assert app.query_one("#b").region.y == app.query_one("#a").region.bottom


async def test_toggle_flips_by_key_space_and_click_and_reports_changes():
    app = Recorder(Toggle("Bold", key="ctrl+b", id="t"))
    async with app.run_test(size=(50, 6)) as pilot:
        toggle = app.query_one("#t", Toggle)
        toggle.focus()
        await pilot.press("space")
        assert toggle.pressed and toggle.has_class("-pressed")
        await pilot.press("ctrl+b")
        assert not toggle.pressed
        await pilot.click("#t")
        await pilot.pause()
        assert app.events == [("toggle", "t", True), ("toggle", "t", False), ("toggle", "t", True)]


async def test_single_toggle_group_keeps_at_most_one_pressed():
    group = ToggleGroup(
        Toggle("Left", value="l", id="l"),
        Toggle("Center", value="c", id="c"),
        Toggle("Right", value="r", id="r"),
        value="c",
        id="g",
    )
    app = Recorder(group)
    async with app.run_test(size=(60, 6)) as pilot:
        assert group.value == "c"
        app.query_one("#l").focus()
        await pilot.press("space")
        assert group.value == "l" and not app.query_one("#c", Toggle).pressed
        await pilot.press("space")  # Pressing the pressed one clears the group.
        assert group.value is None
        await pilot.press("right", "right", "space")
        assert group.value == "r"
        assert app.events[-1] == ("group", "g", "r")


async def test_multiple_toggle_group_collects_values_and_rejects_a_bad_type():
    group = ToggleGroup(
        Toggle("Bold", value="b", id="b"),
        Toggle("Italic", value="i", id="i"),
        type="multiple",
        value=("b",),
        id="g",
    )
    app = Recorder(group)
    async with app.run_test(size=(60, 6)) as pilot:
        assert group.value == ("b",)
        app.query_one("#i").focus()
        await pilot.press("space")
        assert group.value == ("b", "i")
    with pytest.raises(ValueError):
        ToggleGroup(type="triple")
