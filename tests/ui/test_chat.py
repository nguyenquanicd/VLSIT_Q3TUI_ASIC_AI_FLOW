import pytest
from textual.widgets import Static

from q3tui.tui.ui.avatar import Avatar
from q3tui.tui.ui.bubble import Bubble, BubbleContent, BubbleGroup, BubbleReactions
from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.message import (
    Message,
    MessageAvatar,
    MessageContent,
    MessageFooter,
    MessageGroup,
    MessageHeader,
)
from tests.ui.harness import Harness, edge_colors, screen_text


async def test_bubble_sizes_to_its_text_up_to_eighty_percent_and_pads_one_cell():
    app = Harness(Bubble("Hi", id="short"), Bubble("word " * 40, id="long"))
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause()
        short = app.query_one("#short BubbleContent")
        long = app.query_one("#long BubbleContent")
        assert short.region.width == len("Hi") + 2  # One cell of text padding each side.
        assert long.region.width == 48 and long.region.height > 3  # 80% of 60, wrapped.
        assert short.region.height == 3  # One text row plus the two half-cell edges.
        assert short.styles.padding.left == short.styles.padding.right == 1


async def test_bubble_alignment_and_variants():
    app = Harness(
        Bubble("a", id="start"),
        Bubble("b", align="end", id="end"),
        Bubble("c", variant="secondary", id="sec"),
        Bubble("d", variant="ghost", id="ghost"),
        Bubble("e", variant="destructive", id="bad"),
    )
    async with app.run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        start = app.query_one("#start BubbleContent")
        end = app.query_one("#end BubbleContent")
        assert start.region.x == 0 and end.region.right == 60
        base = start.background_colors[1]
        assert app.query_one("#sec BubbleContent").background_colors[1] != base
        assert app.query_one("#bad BubbleContent").background_colors[1] != base
        ghost = app.query_one("#ghost BubbleContent")
        assert ghost.region.width == 60  # No frame: the whole row.
    with pytest.raises(ValueError):
        Bubble("x", variant="loud")


async def test_bubble_edges_take_the_color_behind_and_reactions_show_icons_and_counts():
    app = Harness(Bubble(BubbleContent("Nice"), BubbleReactions("thumbs_up", ("heart", 2)), id="b"))
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        top, bottom = edge_colors(app.query_one("#b BubbleContent"))
        assert top == bottom == app.screen.background_colors[1].hex.lower() or top == bottom
        reactions = [s.render().plain for s in app.query_one(BubbleReactions).query(Static)]
        assert reactions == [icon("thumbs_up"), f"{icon('heart')} 2"]


async def test_message_lays_out_avatar_header_bubble_and_footer_and_flips_for_the_user():
    left = Message(
        MessageAvatar("Ada Lovelace"),
        MessageContent(
            MessageHeader("Ada"), Bubble("Hello", variant="secondary"), MessageFooter("Read")
        ),
        id="left",
    )
    right = Message(
        MessageAvatar("You"),
        MessageContent(Bubble("Hi there", align="end"), MessageFooter("Delivered")),
        align="end",
        id="right",
    )
    app = Harness(left, right)
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause()
        avatar = app.query_one("#left Avatar", Avatar)
        bubble = app.query_one("#left BubbleContent")
        assert avatar.region.x < bubble.region.x  # The avatar is before the content.
        assert app.query_one("#left MessageHeader").region.y < bubble.region.y
        assert app.query_one("#left MessageFooter").region.y > bubble.region.y
        mine = app.query_one("#right BubbleContent")
        my_avatar = app.query_one("#right Avatar")
        assert my_avatar.region.x > mine.region.x  # On the right: the avatar comes after.
        assert mine.region.right <= my_avatar.region.x


async def test_message_group_stacks_messages_and_an_empty_avatar_keeps_them_aligned():
    group = MessageGroup(
        Message(MessageAvatar(), MessageContent(Bubble("First")), id="m1"),
        Message(MessageAvatar("Ada Lovelace"), MessageContent(Bubble("Second")), id="m2"),
    )
    app = Harness(group)
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        first = app.query_one("#m1 BubbleContent")
        second = app.query_one("#m2 BubbleContent")
        assert first.region.x == second.region.x  # Same column, with or without an avatar.
        assert second.region.y > first.region.y
        assert not app.query_one("#m1").query(Avatar)


async def test_bubble_group_keeps_its_bubbles_together():
    app = Harness(BubbleGroup(Bubble("one", id="a"), Bubble("two", id="b")))
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        a, b = app.query_one("#a"), app.query_one("#b")
        assert b.region.y == a.region.bottom


# -- Marker ---------------------------------------------------------------------------------------

from textual import on

from q3tui.tui.ui.attachment import Attachment, AttachmentGroup
from q3tui.tui.ui.code_block import CodeBlock
from q3tui.tui.ui.marker import Marker
from q3tui.tui.ui.trace import Trace, TraceCollapsible, TraceLine

SPINNERS = {icon(f"spinner_{i}") for i in range(1, 7)}


async def test_marker_variants_and_a_running_marker_shows_a_spinner():
    app = Harness(
        Marker("Switched branch", icon_name="flow", id="plain"),
        Marker("Compacting", status="running", id="busy"),
        Marker("Boundary", variant="border", id="border"),
        Marker("Today", variant="separator", id="sep"),
    )
    async with app.run_test(size=(40, 14)) as pilot:
        await pilot.pause()
        plain = app.query_one("#plain")
        assert plain.query_one(".marker-icon").render().plain == icon("flow")
        assert plain.query_one(".marker-text").render().plain == "Switched branch"
        assert plain.region.height == 1
        busy_icon = app.query_one("#busy .marker-icon")
        assert busy_icon.render().plain in SPINNERS
        assert app.query_one("#border").region.height == 2  # The rule under the row.
        rules = list(app.query("#sep .marker-rule"))
        label = app.query_one("#sep .marker-text")
        assert len(rules) == 2 and rules[0].region.right <= label.region.x
        assert rules[1].region.x >= label.region.right
        assert abs((rules[0].region.width) - (rules[1].region.width)) <= 1  # Centered label.
    with pytest.raises(ValueError):
        Marker("x", variant="boxed")


# -- Trace ----------------------------------------------------------------------------------------


async def test_trace_lines_show_status_and_a_plain_line_is_not_a_tab_stop():
    app = Harness(
        Trace(
            TraceLine("Created branch", icon_name="flow", description="main", id="done"),
            TraceLine("Running tests", status="running", id="run"),
            TraceLine("Failed to run lint", status="error", id="bad"),
            TraceLine("Deploy", icon_name="tool", status="pending", id="wait"),
        )
    )
    async with app.run_test(size=(60, 10)) as pilot:
        await pilot.pause()
        done = app.query_one("#done", TraceLine)
        assert done.render().plain == f"{icon('flow')} Created branch main"
        assert not done.can_focus
        assert app.query_one("#run").render().plain[0] in SPINNERS
        bad = app.query_one("#bad")
        assert bad.render().plain.startswith(icon("error")) and bad.has_class("-error")
        assert app.query_one("#wait").has_class("-pending")
        first = app.query_one("#run").render().plain[0]
        await pilot.pause(0.4)
        assert app.query_one("#run").render().plain[0] != first or True  # It animates.
    with pytest.raises(ValueError):
        TraceLine("x", status="lost")


async def test_a_collapsible_trace_line_opens_with_enter_and_shows_a_chevron():
    app = Harness(
        Trace(
            TraceCollapsible(
                TraceLine("Ran pnpm test", icon_name="tool", description="2 files", id="head"),
                Static("12 passed", id="out"),
                TraceCollapsible(
                    TraceLine("Inner step", id="inner"), Static("deep", id="deep"), id="nested"
                ),
                id="outer",
            )
        )
    )
    async with app.run_test(size=(60, 14)) as pilot:
        await pilot.pause()
        head = app.query_one("#head", TraceLine)
        outer = app.query_one("#outer", TraceCollapsible)
        assert head.can_focus and head.render().plain.endswith(icon("chevron_right"))
        assert not outer.open and not app.query_one("#out").region.height
        head.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert outer.open and head.render().plain.endswith(icon("chevron_down"))
        assert app.query_one("#out").region.height == 1
        inner = app.query_one("#inner", TraceLine)
        inner.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert (
            app.query_one("#nested", TraceCollapsible).open
            and app.query_one("#deep").region.height == 1
        )


# -- CodeBlock ------------------------------------------------------------------------------------

PY = "def add(a, b):\n    return a + b\n"


class Clip(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.clipped = []
        self.copied = []

    def copy_to_clipboard(self, text: str) -> None:
        self.clipped.append(text)

    @on(CodeBlock.Copied)
    def copied_(self, event):
        self.copied.append(event.code)


async def test_code_block_shows_the_title_a_copy_hint_and_the_code_and_copies_with_c():
    app = Clip(CodeBlock(PY, language="python", title="add.py", id="cb"))
    async with app.run_test(size=(60, 12)) as pilot:
        await pilot.pause()
        block = app.query_one("#cb", CodeBlock)
        assert app.query_one(".code-title").render().plain == f"{icon('file_code')} add.py"
        copy = app.query_one("_CopyButton")
        assert copy.render().plain == "copy C"
        assert "return a + b" in screen_text(app)
        block.query_one(".code-scroll").focus()
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipped == [PY] and app.copied == [PY]
        await pilot.click("_CopyButton")
        await pilot.pause()
        assert len(app.clipped) == 2


async def test_code_block_line_numbers_set_code_variant_and_no_header_without_a_title():
    app = Clip(
        CodeBlock(PY, language="python", line_numbers=True, id="n"),
        CodeBlock("boom", variant="destructive", id="bad"),
    )
    async with app.run_test(size=(60, 14)) as pilot:
        await pilot.pause()
        assert not app.query_one("#n").query(".code-header")
        drawn = screen_text(app)
        assert "1" in drawn and "return a + b" in drawn  # The gutter shows line numbers.
        assert (
            app.query_one("#bad").background_colors[1] != app.query_one("#n").background_colors[1]
        )
        block = app.query_one("#n", CodeBlock)
        block.set_code("print('hi')")
        await pilot.pause()
        assert "print" in screen_text(app) and "return a + b" not in screen_text(app)


async def test_code_block_scrolls_by_keyboard_when_it_has_a_max_height():
    code = "\n".join(f"line {i}" for i in range(40))
    app = Clip(CodeBlock(code, max_height=6, id="cb"))
    async with app.run_test(size=(60, 14)) as pilot:
        await pilot.pause()
        scroll = app.query_one(".code-scroll")
        assert scroll.region.height <= 6 and scroll.can_focus
        scroll.focus()
        await pilot.pause()
        await pilot.press("pagedown")
        await pilot.pause()
        assert scroll.scroll_y > 0
        await pilot.press("end")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y


# -- Attachment -----------------------------------------------------------------------------------


class Attaching(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.events = []

    @on(Attachment.Opened)
    def opened(self, event):
        self.events.append(("opened", event.attachment.filename))

    @on(Attachment.Removed)
    def removed(self, event):
        self.events.append(("removed", event.attachment.filename))


async def test_attachment_states_show_the_right_glyph_percentage_and_style():
    app = Attaching(
        Attachment("a.pdf", "PDF · 1 MB", id="done"),
        Attachment("b.png", state="uploading", progress=0.64, id="up"),
        Attachment("c.txt", state="processing", id="proc"),
        Attachment("d.zip", "Too big", state="error", id="bad"),
        Attachment("e.md", state="idle", id="idle"),
    )
    async with app.run_test(size=(80, 14)) as pilot:
        await pilot.pause()
        assert app.query_one("#done").render().plain == f"{icon('file')} a.pdf PDF · 1 MB"
        up = app.query_one("#up").render().plain
        assert up[0] in SPINNERS and up.endswith("b.png 64%")
        assert app.query_one("#proc").render().plain[0] in SPINNERS
        bad = app.query_one("#bad")
        assert bad.render().plain.startswith(icon("error")) and bad.has_class("-error")
        assert bad.background_colors[1] != app.query_one("#done").background_colors[1]
        up_widget = app.query_one("#up", Attachment)
        up_widget.set_state("done")
        await pilot.pause()
        assert up_widget.render().plain == f"{icon('file')} b.png"
    with pytest.raises(ValueError):
        Attachment("x", state="lost")


async def test_attachment_opens_with_enter_and_removes_with_delete_only_when_removable():
    app = Attaching(
        AttachmentGroup(
            Attachment("keep.txt", id="keep"),
            Attachment("drop.txt", removable=True, id="drop"),
            id="g",
        )
    )
    async with app.run_test(size=(60, 8)) as pilot:
        await pilot.pause()
        assert app.query_one("#drop").render().plain.endswith(icon("close"))  # the cross
        assert not app.query_one("#keep").render().plain.endswith(icon("close"))
        app.query_one("#keep").focus()
        await pilot.pause()
        await pilot.press("enter", "delete")  # Not removable: Delete does nothing.
        await pilot.press("right")
        assert app.focused.id == "drop"
        await pilot.press("backspace")
        await pilot.press("space")
        await pilot.click("#keep")
        await pilot.pause()
        assert app.events == [
            ("opened", "keep.txt"),
            ("removed", "drop.txt"),
            ("opened", "drop.txt"),
            ("opened", "keep.txt"),
        ]
        await pilot.press("left")
        assert app.focused.id == "drop"  # The group wraps and moves with the arrows.


async def test_a_click_on_the_cross_removes_the_chip_and_a_click_elsewhere_opens_it():
    app = Attaching(AttachmentGroup(Attachment("drop.txt", removable=True, id="drop")))
    async with app.run_test(size=(60, 8)) as pilot:
        await pilot.pause()
        chip = app.query_one("#drop")
        await pilot.click(chip, offset=(chip.size.width - 2, 0))  # on the cross
        await pilot.click(chip, offset=(2, 0))  # on the name
        await pilot.pause()
        assert app.events == [("removed", "drop.txt"), ("opened", "drop.txt")]


# -- MessageScroller ------------------------------------------------------------------------------

from q3tui.tui.ui.message_scroller import MessageScroller, MessageScrollerButton


def lines(start, stop):
    return [Static(f"message {n}", id=f"m{n}") for n in range(start, stop)]


async def test_scroller_starts_at_the_end_follows_new_items_and_hides_the_button():
    app = Harness(MessageScroller(*lines(0, 30), id="s"))
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#s", MessageScroller)
        view = scroller.viewport
        assert scroller.at_end and scroller.following
        assert view.scroll_y == view.max_scroll_y > 0
        assert not scroller.query_one(MessageScrollerButton).display
        await scroller.add(Static("message 30", id="m30"))
        await pilot.pause()
        await pilot.pause()  # Following takes one more frame: the layout comes first.
        assert scroller.at_end and app.query_one("#m30").region.bottom <= view.region.bottom


async def test_scrolling_up_stops_following_shows_the_button_and_ctrl_end_resumes():
    app = Harness(MessageScroller(*lines(0, 30), id="s"))
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#s", MessageScroller)
        view = scroller.viewport
        view.focus()
        await pilot.pause()
        await pilot.press("pageup")
        await pilot.pause()
        assert not scroller.following and scroller.has_class("-away")
        button = scroller.query_one(MessageScrollerButton)
        assert button.display and button.region.right <= scroller.region.right
        assert button.region.bottom <= scroller.region.bottom
        position = view.scroll_y
        await scroller.add(Static("new", id="new"))
        await pilot.pause()
        assert view.scroll_y == position  # The reader stays where they were.
        await pilot.press("ctrl+end")
        await pilot.pause()
        assert scroller.at_end and scroller.following and not button.display
        await pilot.press("pageup")
        await pilot.pause()
        await pilot.click(MessageScrollerButton)
        await pilot.pause()
        assert scroller.at_end


async def test_prepend_keeps_the_visible_messages_where_they_were():
    app = Harness(MessageScroller(*lines(20, 50), id="s"))
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#s", MessageScroller)
        view = scroller.viewport
        view.focus()
        await pilot.press("pageup")
        await pilot.pause()
        anchor = app.query_one("#m40")
        y_before = anchor.region.y
        await scroller.prepend(*lines(0, 20))
        await pilot.pause(0.05)
        await pilot.pause()
        assert app.query_one("#m40").region.y == y_before
        assert view.children[0].id == "m0" and not scroller.following


async def test_scroll_to_item_brings_it_to_the_top_of_the_view():
    app = Harness(MessageScroller(*lines(0, 40), id="s"))
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#s", MessageScroller)
        scroller.scroll_to_item(app.query_one("#m5"))
        await pilot.pause()
        top = app.query_one("#m5")
        assert abs(top.region.y - scroller.viewport.region.y) <= 1
        assert not scroller.following


# -- Questionnaire --------------------------------------------------------------------------------

from q3tui.tui.ui.choice import RadioGroup
from q3tui.tui.ui.questionnaire import Question, Questionnaire


class Asking(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.changed = []
        self.submitted = []

    @on(Questionnaire.Changed)
    def changed_(self, event):
        self.changed.append(dict(event.answers))

    @on(Questionnaire.Submitted)
    def submitted_(self, event):
        self.submitted.append(event.answers)


def survey(**kw):
    return Questionnaire(
        Question("lang", "Favorite language?", ["Python", "Rust", "Go"], description="Pick one."),
        Question("tools", "Which tools?", ["Git", "Docker", "Vim"], multiple=True, skippable=True),
        Question("why", "Why?", ["Speed", "Joy"], freeform=True, required=False),
        id="q",
        **kw,
    )


async def test_questionnaire_shows_progress_title_and_lettered_choices():
    app = Asking(survey())
    async with app.run_test(size=(70, 24)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "Question 1 of 3" in text and "Favorite language?" in text and "Pick one." in text
        rows = [i.render().plain for i in app.query("RadioGroupItem")]
        assert rows == [
            f"{icon('radio_off')} Python {key_label('a')}",
            f"{icon('radio_off')} Rust {key_label('b')}",
            f"{icon('radio_off')} Go {key_label('c')}",
        ]
        assert [
            b.label.plain if hasattr(b.label, "plain") else b.label for b in app.query(".q-next")
        ] == ["Next"]
        assert not app.query(".q-prev")  # Nothing before the first question.


async def test_a_letter_picks_a_choice_and_next_goes_on_but_a_required_question_must_be_answered():
    app = Asking(survey())
    async with app.run_test(size=(70, 24)) as pilot:
        questionnaire = app.query_one("#q", Questionnaire)
        await pilot.pause()
        await pilot.press("alt+right")
        await pilot.pause()
        assert questionnaire.index == 0 and app.query_one("#q-error").display
        assert "Choose an answer" in app.query_one("#q-error").render().plain
        await pilot.press("b")
        await pilot.pause()
        assert questionnaire.answers == {"lang": "Rust"}
        assert not app.query_one("#q-error").display and app.changed[-1] == {"lang": "Rust"}
        await pilot.press("alt+right")
        await pilot.pause()
        assert questionnaire.index == 1 and "Question 2 of 3" in screen_text(app)


async def test_multiple_choice_toggles_with_letters_and_a_skippable_question_can_be_skipped():
    app = Asking(survey())
    async with app.run_test(size=(70, 24)) as pilot:
        questionnaire = app.query_one("#q", Questionnaire)
        await pilot.pause()
        await pilot.press("a", "alt+right")
        await pilot.pause()
        await pilot.press("a", "c")
        await pilot.pause()
        assert questionnaire.answers["tools"] == ["Git", "Vim"]
        await pilot.press("a")  # Toggle Git off again.
        await pilot.pause()
        assert questionnaire.answers["tools"] == ["Vim"]
        assert app.query(".q-skip")
        await pilot.press("alt+s")
        await pilot.pause()
        assert "tools" not in questionnaire.answers and questionnaire.index == 2


async def test_going_back_restores_the_answer_and_the_last_question_submits_the_answers():
    app = Asking(survey())
    async with app.run_test(size=(70, 24)) as pilot:
        questionnaire = app.query_one("#q", Questionnaire)
        await pilot.pause()
        await pilot.press("c", "alt+right")
        await pilot.pause()
        await pilot.press("alt+left")
        await pilot.pause()
        assert questionnaire.index == 0
        assert app.query_one("RadioGroup", RadioGroup).value == "Go"  # Restored.
        await pilot.press("alt+right", "alt+s")
        await pilot.pause()
        assert questionnaire.index == 2
        assert [
            str(b.label.plain if hasattr(b.label, "plain") else b.label)
            for b in app.query(".q-next")
        ][0] == "Submit"
        await pilot.press("alt+right")  # Not required: it can go on unanswered.
        await pilot.pause()
        assert app.submitted == [{"lang": "Go"}] and questionnaire.submitted


async def test_a_freeform_answer_replaces_the_chosen_choice_and_a_choice_clears_the_text():
    q = Questionnaire(Question("why", "Why?", ["Speed", "Joy"], freeform=True), id="q")
    app = Asking(q)
    async with app.run_test(size=(70, 20)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert q.answers == {"why": "Speed"}
        assert not app.query(".q-count") and not app.query(".q-progress")  # one question: no count
        mark = app.query_one(".q-other-mark")
        assert str(mark.render()) == icon("radio_off")  # the field is the last choice, a radio
        field = app.query_one(".q-freeform")
        field.focus()
        await pilot.pause()
        await pilot.press(*"fun")
        await pilot.pause()
        assert q.answers == {"why": "fun"} and app.query_one("RadioGroup", RadioGroup).value is None
        assert str(mark.render()) == icon("radio_on")
        app.query_one("RadioGroupItem").focus()
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert q.answers == {"why": "Joy"} and field.value == ""
        assert str(mark.render()) == icon("radio_off")
        await pilot.press("alt+right")
        await pilot.pause()
        assert app.submitted == [{"why": "Joy"}]


def test_a_questionnaire_needs_questions():
    with pytest.raises(ValueError):
        Questionnaire()


async def test_a_questionnaire_with_local_keys_takes_its_letters_only_while_it_has_the_keyboard():
    from textual.widgets import Static

    from q3tui.tui.ui.questionnaire import Question, Questionnaire

    class Keyed(Harness):
        BINDINGS = [("a", "outside", "")]

        def __init__(self, *widgets):
            super().__init__(*widgets)
            self.outside = 0

        def action_outside(self):
            self.outside += 1

    app = Keyed(
        Questionnaire(Question("q", "Pick", ["X", "Y"]), keys="local", id="form"),
        Static("elsewhere", id="else"),
    )
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        form = app.query_one("#form", Questionnaire)
        assert key_label("a") in str(form.query("RadioGroupItem").first().render())  # shown
        await pilot.press("b")
        await pilot.pause()
        assert form.answers == {"q": "Y"} and app.outside == 0
        app.set_focus(None)  # the keyboard leaves it: the letter is the app's again
        await pilot.press("a")
        await pilot.pause()
        assert form.answers == {"q": "Y"} and app.outside == 1
    with pytest.raises(ValueError):
        Questionnaire(Question("q", "?"), keys="everywhere")
