import pytest
from textual.containers import Vertical
from textual.widgets import Static

from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle
from q3tui.tui.ui.card import (
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
)
from q3tui.tui.ui.empty import (
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
)
from q3tui.tui.ui.icons import icon
from tests.ui.harness import Harness, edge_colors


def alert(variant="default", **kw):
    return Alert(
        AlertTitle("Heads up"), AlertDescription("Something changed."), variant=variant, **kw
    )


@pytest.mark.parametrize(
    ("variant", "glyph"),
    [
        ("default", "about"),
        ("destructive", "error"),
        ("success", "selected"),
        ("warning", "warning"),
    ],
)
async def test_alert_shows_its_variant_icon_title_and_description(variant, glyph):
    app = Harness(alert(variant, id="a"))
    async with app.run_test(size=(50, 10)) as pilot:
        await pilot.pause()
        box = app.query_one("#a", Alert)
        assert box.query_one(".alert-icon").render().plain == icon(glyph)
        assert box.query_one(AlertTitle).render().plain == "Heads up"
        assert box.query_one(AlertDescription).render().plain == "Something changed."
        # Two text rows plus the two half-cell edge rows; text starts one cell inside.
        assert box.region.height == 4
        assert box.query_one(".alert-icon").region.x == box.region.x + 1


async def test_destructive_alert_has_its_own_fill_and_a_custom_icon_overrides():
    app = Harness(alert(id="a"), alert("destructive", id="d"), alert(icon_name="inbox", id="c"))
    async with app.run_test(size=(50, 20)) as pilot:
        await pilot.pause()
        assert app.query_one("#d").background_colors[1] != app.query_one("#a").background_colors[1]
        assert app.query_one("#c .alert-icon").render().plain == icon("inbox")


async def test_alert_edges_take_the_color_of_what_it_sits_on():
    app = Harness(Vertical(alert(id="a"), id="panel"))
    app.CSS = "#panel { background: #336699; height: 8; }"
    async with app.run_test(size=(50, 10)) as pilot:
        await pilot.pause()
        assert edge_colors(app.query_one("#a")) == ("#336699", "#336699")


async def test_card_composes_header_action_content_and_footer():
    card = Card(
        CardHeader(
            CardTitle("Plan"),
            CardDescription("Your current plan"),
            CardAction(Static("Edit", id="edit")),
        ),
        CardContent(Static("Body", id="body")),
        CardFooter(Static("Footer", id="foot")),
        id="card",
    )
    app = Harness(card)
    async with app.run_test(size=(50, 16)) as pilot:
        await pilot.pause()
        title = app.query_one(CardTitle)
        assert title.region.x == card.region.x + 1  # One cell of text padding.
        edit = app.query_one("#edit")
        assert edit.region.y == title.region.y  # The action is level with the title.
        assert edit.region.right <= card.region.right - 1
        header = app.query_one(CardHeader)
        body = app.query_one(CardContent)
        footer = app.query_one(CardFooter)
        assert body.region.y == header.region.bottom + 1  # A blank row between the sections.
        assert footer.region.y == body.region.bottom + 1
        assert card.region.height == footer.region.bottom - card.region.y + 1  # + bottom edge.


async def test_card_without_a_footer_ends_after_its_content():
    card = Card(CardHeader(CardTitle("T")), CardContent(Static("Body")), id="card")
    app = Harness(card)
    async with app.run_test(size=(50, 12)) as pilot:
        await pilot.pause()
        assert card.region.bottom == app.query_one(CardContent).region.bottom + 1


async def test_empty_centers_its_media_title_description_and_actions():
    empty = Empty(
        EmptyHeader(
            EmptyMedia("inbox"), EmptyTitle("No messages"), EmptyDescription("Nothing yet.")
        ),
        EmptyContent(Static("Compose", id="act")),
        id="e",
    )
    app = Harness(empty)
    async with app.run_test(size=(40, 14)) as pilot:
        await pilot.pause()
        title = app.query_one(EmptyTitle)
        assert title.render().plain == "No messages"
        assert title.styles.text_align == "center"
        assert app.query_one(EmptyMedia).render().plain == icon("inbox")
        act = app.query_one("#act")
        centre = (act.region.x + act.region.right) / 2
        assert abs(centre - (empty.region.x + empty.region.right) / 2) <= 1
