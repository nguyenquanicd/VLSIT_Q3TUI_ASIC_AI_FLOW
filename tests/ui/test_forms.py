import pytest
from textual import on
from textual.validation import Length
from textual.widgets import Input as TextualInput

from q3tui.tui.ui.choice import Checkbox, RadioGroup, RadioGroupItem, Switch
from q3tui.tui.ui.field import Field, FieldDescription, FieldError, FieldGroup, FieldLabel, Label
from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.input import Input, InputGroup, InputGroupAddon, Textarea
from q3tui.tui.ui.slider import Slider
from tests.ui.harness import Harness


class Recorder(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.events = []

    @on(Checkbox.Changed)
    def checkbox(self, event):
        self.events.append(("checkbox", event.checkbox.id, event.checked))

    @on(Switch.Changed)
    def switch(self, event):
        self.events.append(("switch", event.switch.id, event.on))

    @on(RadioGroup.Changed)
    def radio(self, event):
        self.events.append(("radio", event.group.id, event.value))

    @on(Slider.Changed)
    def slider(self, event):
        self.events.append(("slider", event.slider.id, event.value))


async def test_checkbox_states_toggle_by_space_click_and_key_and_report_changes():
    app = Recorder(Checkbox("Agree", key="ctrl+a", id="c"), Checkbox("Off", disabled=True, id="d"))
    async with app.run_test(size=(60, 6)) as pilot:
        box = app.query_one("#c", Checkbox)
        assert box.render().plain == f"{icon('checkbox_off')} Agree {key_label('ctrl+a')}"
        box.focus()
        await pilot.press("space")
        assert box.checked is True and box.render().plain.startswith(icon("checkbox_on"))
        await pilot.press("ctrl+a")
        await pilot.click("#c")
        await pilot.click("#d")
        await pilot.pause()
        assert [e[2] for e in app.events] == [True, False, True]


async def test_an_indeterminate_checkbox_becomes_checked_when_activated():
    app = Recorder(Checkbox("Some", checked="indeterminate", id="c"))
    async with app.run_test(size=(60, 6)) as pilot:
        box = app.query_one("#c", Checkbox)
        assert box.render().plain.startswith(icon("checkbox_mixed"))
        box.focus()
        await pilot.press("enter")
        assert box.checked is True


async def test_switch_flips_and_dims_its_label_while_off():
    app = Recorder(Switch("Wi-Fi", id="s"))
    async with app.run_test(size=(60, 6)) as pilot:
        switch = app.query_one("#s", Switch)
        assert switch.render().plain.startswith(icon("switch_off"))
        off_color = switch.styles.color
        switch.focus()
        await pilot.press("space")
        assert switch.on and switch.has_class("-on")
        assert switch.render().plain.startswith(icon("switch_on"))
        assert switch.styles.color != off_color
        assert app.events == [("switch", "s", True)]


def radios(**kw):
    return RadioGroup(
        RadioGroupItem("Free", "free", id="free"),
        RadioGroupItem("Pro", "pro", id="pro", disabled=True),
        RadioGroupItem("Team", "team", id="team"),
        id="g",
        **kw,
    )


async def test_radio_group_selects_with_arrows_skips_disabled_and_has_one_tab_stop():
    app = Recorder(Input(id="before"), radios(value="free"), Input(id="after"))
    async with app.run_test(size=(60, 12)) as pilot:
        group = app.query_one("#g", RadioGroup)
        assert group.value == "free"
        assert [i.can_focus for i in group.items] == [True, False, False]
        app.query_one("#before").focus()
        await pilot.press("tab")
        assert app.focused.id == "free"  # Tab enters on the selected item...
        await pilot.press("tab")
        assert app.focused.id == "after"  # ...and leaves the group in one more press.
        app.query_one("#free").focus()
        await pilot.pause()
        await pilot.press("down")
        assert group.value == "team" and app.focused.id == "team"  # "Pro" is disabled.
        assert [i.can_focus for i in group.items] == [False, False, True]
        await pilot.press("down")
        assert group.value == "free"  # Wraps.
        await pilot.press("up")
        assert group.value == "team"
        await pilot.press("left")
        assert group.value == "free"
        assert [e[2] for e in app.events] == ["team", "free", "team", "free"]
        assert [e[2] for e in app.events] == ["team", "free", "team", "free"][: len(app.events)]


async def test_radio_item_selects_on_space_and_click_and_reports_only_changes():
    app = Recorder(radios())
    async with app.run_test(size=(60, 8)) as pilot:
        group = app.query_one("#g", RadioGroup)
        assert group.value is None
        assert [i.can_focus for i in group.items] == [True, False, False]  # Nothing selected.
        app.query_one("#free").focus()
        await pilot.press("space", "space")
        await pilot.click("#team")
        await pilot.pause()
        assert group.value == "team"
        assert app.events == [("radio", "g", "free"), ("radio", "g", "team")]
        assert app.query_one("#team").render().plain.startswith(icon("radio_on"))


async def test_input_has_text_padding_half_cell_edges_and_changes_fill_on_focus_and_error():
    app = Harness(
        Input(placeholder="Name", validators=[Length(minimum=3)], validate_on=["changed"], id="i"),
        Input(id="o"),
    )
    async with app.run_test(size=(40, 10)) as pilot:
        field = app.query_one("#i", Input)
        assert field.region.height == 3  # One text row plus the two half-cell edges.
        assert field.styles.padding.left == field.styles.padding.right == 1
        app.set_focus(None)
        await pilot.pause()
        resting = field.background_colors[1]
        field.focus()
        await pilot.pause()
        focused = field.background_colors[1]
        assert focused != resting
        await pilot.press("a")
        await pilot.pause()
        assert field.has_class("-invalid")
        assert field.background_colors[1] not in (focused, resting)
        await pilot.press("b", "c")
        await pilot.pause()
        assert not field.has_class("-invalid")


async def test_textarea_takes_its_row_count_and_the_same_look():
    app = Harness(Textarea("hello", rows=4, id="t"))
    async with app.run_test(size=(40, 12)) as pilot:
        area = app.query_one("#t", Textarea)
        assert area.region.height == 4 + 2
        assert area.text == "hello"
        assert area.styles.padding.left == 1
        app.set_focus(None)
        await pilot.pause()
        resting = area.background_colors[1]
        area.focus()
        await pilot.pause()
        assert area.background_colors[1] != resting


async def test_input_group_shares_one_fill_and_deepens_while_focused():
    group = InputGroup(
        InputGroupAddon("find", icon_name="search"), Input(placeholder="Search", id="i"), id="g"
    )
    app = Harness(group)
    async with app.run_test(size=(50, 8)) as pilot:
        await pilot.pause()
        addon = app.query_one(InputGroupAddon)
        assert addon.region.x == group.region.x
        assert app.query_one("#i").region.height == 1  # The group provides the edges.
        assert group.region.height == 3
        app.set_focus(None)
        await pilot.pause()
        resting = group.background_colors[1]
        app.query_one("#i").focus()
        await pilot.pause()
        assert group.background_colors[1] != resting
        assert app.query_one("#i").background_colors[1] == group.background_colors[1]


async def test_a_label_focuses_its_control_even_when_it_sits_inside_a_group():
    app = Harness(
        Label("Name", for_="#name", required=True, id="l"),
        Input(id="name"),
        Label("Search", for_="#grp", id="l2"),
        InputGroup(Input(id="inner"), id="grp"),
    )
    async with app.run_test(size=(40, 14)) as pilot:
        assert app.query_one("#l", Label).render().plain == "Name *"
        await pilot.click("#l")
        assert app.focused.id == "name"
        await pilot.click("#l2")
        assert app.focused.id == "inner"


async def test_field_links_its_label_shows_and_clears_an_error_and_marks_the_control():
    field = Field(
        FieldLabel("Email", id="lab"),
        Input(id="email"),
        FieldDescription("We never share it."),
        FieldError(id="err"),
        id="f",
    )
    app = Harness(FieldGroup(field, Field(FieldLabel("Other"), Input(id="other"))))
    async with app.run_test(size=(40, 20)) as pilot:
        assert not app.query_one("#err").display
        await pilot.click("#lab")
        assert app.focused.id == "email"  # The label found its control by itself.
        field.set_error("Not an email")
        await pilot.pause()
        assert app.query_one("#err").display
        assert app.query_one("#err", FieldError).render().plain == "Not an email"
        assert field.has_class("-invalid") and app.query_one("#email").has_class("-invalid")
        field.set_error(None)
        await pilot.pause()
        assert not app.query_one("#err").display
        assert not app.query_one("#email").has_class("-invalid")
        first, second = app.query(Field)
        assert second.region.y == first.region.bottom + 1  # FieldGroup spaces its fields.


async def test_horizontal_field_puts_the_label_beside_the_control():
    field = Field(
        Switch("Dark mode", id="sw"),
        FieldDescription("Use the dark theme."),
        orientation="horizontal",
    )
    app = Harness(field)
    async with app.run_test(size=(60, 6)) as pilot:
        await pilot.pause()
        switch, note = app.query_one("#sw"), app.query_one(FieldDescription)
        assert note.region.y == switch.region.y and note.region.x > switch.region.right


async def test_slider_moves_by_step_page_home_end_and_snaps_and_clamps():
    app = Recorder(Slider(50, step=5, label="Volume", id="s"))
    async with app.run_test(size=(60, 4)) as pilot:
        slider = app.query_one("#s", Slider)
        slider.focus()
        await pilot.press("right")
        assert slider.value == 55
        await pilot.press("left", "left", "down")
        assert slider.value == 40
        await pilot.press("pageup")
        assert slider.value == 90
        await pilot.press("pageup")
        assert slider.value == 100  # Clamped.
        await pilot.press("home")
        assert slider.value == 0
        await pilot.press("end")
        assert slider.value == 100
        slider.set_value(47)
        assert slider.value == 45  # Snapped to a step.
        assert app.events[0] == ("slider", "s", 55)
        assert slider.query_one(".slider-value").render().plain == "45"
        assert slider.query_one(".slider-label").render().plain == "Volume"


async def test_slider_fill_follows_the_value_and_a_click_sets_it():
    app = Recorder(Slider(0, id="s", show_value=False))
    async with app.run_test(size=(60, 4)) as pilot:
        slider = app.query_one("#s", Slider)
        track = slider.query_one(".slider-track")
        await pilot.click(".slider-track", offset=(track.region.width - 1, 0))
        await pilot.pause()
        assert slider.value == 100 and app.focused is slider
        await pilot.click(".slider-track", offset=(track.region.width // 2, 0))
        await pilot.pause()
        assert 40 <= slider.value <= 60
        fill = slider.query_one(".slider-fill")
        assert abs(fill.region.width - slider.value / 100 * (track.region.width - 1)) <= 2
        assert not slider.query(".slider-value")


def test_slider_rejects_a_bad_range_and_a_disabled_slider_ignores_keys():
    with pytest.raises(ValueError):
        Slider(0, minimum=5, maximum=5)
    with pytest.raises(ValueError):
        Slider(0, step=0)


async def test_a_disabled_slider_does_not_react_to_keys():
    app = Recorder(Slider(10, disabled=True, id="s"))
    async with app.run_test(size=(60, 4)) as pilot:
        app.query_one("#s").focus()
        await pilot.press("right")
        assert app.query_one("#s", Slider).value == 10
        assert TextualInput  # Keep the Textual import honest: ours subclasses it.
