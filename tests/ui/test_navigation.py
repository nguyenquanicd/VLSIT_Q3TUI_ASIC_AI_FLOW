import pytest
from textual import on
from textual.widgets import Static

from q3tui.tui.ui.breadcrumb import Breadcrumb, BreadcrumbEllipsis, BreadcrumbItem, BreadcrumbPage
from q3tui.tui.ui.collapsible import (
    Accordion,
    AccordionItem,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
)
from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.input import Input
from q3tui.tui.ui.pagination import Pagination, page_window
from q3tui.tui.ui.sidebar import Sidebar, SidebarGroup, SidebarMenuItem
from q3tui.tui.ui.tabs import Tabs, TabsContent, TabsList, TabsTrigger
from tests.ui.harness import Harness


class Recorder(Harness):
    def __init__(self, *widgets):
        super().__init__(*widgets)
        self.events = []

    @on(Tabs.Changed)
    def tabs(self, event):
        self.events.append(("tabs", event.value))

    @on(Breadcrumb.Navigate)
    def crumbs(self, event):
        self.events.append(("crumb", event.value))

    @on(Pagination.Changed)
    def pages(self, event):
        self.events.append(("page", event.page))

    @on(Collapsible.Toggled)
    def toggled(self, event):
        self.events.append(("toggled", event.collapsible.id, event.open))

    @on(Sidebar.Selected)
    def sidebar(self, event):
        self.events.append(("sidebar", event.value))


def make_tabs(**kw):
    return Tabs(
        TabsList(
            TabsTrigger("Account", "account", id="t1"),
            TabsTrigger("Billing", "billing", id="t2", disabled=True),
            TabsTrigger("Team", "team", id="t3"),
        ),
        TabsContent("account", Static("Account body", id="c1")),
        TabsContent("billing", Static("Billing body", id="c2")),
        TabsContent("team", Static("Team body", id="c3")),
        id="tabs",
        **kw,
    )


async def test_tabs_show_only_the_active_content_and_move_with_the_arrows():
    app = Recorder(make_tabs())
    async with app.run_test(size=(60, 12)) as pilot:
        tabs = app.query_one("#tabs", Tabs)
        await pilot.pause()
        assert tabs.value == "account"
        assert [c.display for c in tabs.query(TabsContent)] == [True, False, False]
        assert [t.can_focus for t in tabs.triggers] == [True, False, False]  # One Tab stop.
        app.query_one("#t1").focus()
        await pilot.pause()
        await pilot.press("right")  # Skips the disabled tab.
        assert tabs.value == "team" and app.focused.id == "t3"
        assert [c.display for c in tabs.query(TabsContent)] == [False, False, True]
        await pilot.press("right")
        assert tabs.value == "account"  # Wraps.
        await pilot.press("end")
        assert tabs.value == "team"
        await pilot.press("home")
        assert tabs.value == "account"
        assert app.events == [
            ("tabs", "team"),
            ("tabs", "account"),
            ("tabs", "team"),
            ("tabs", "account"),
        ]


async def test_tabs_initial_value_click_select_and_unknown_tab():
    app = Recorder(make_tabs(value="team"))
    async with app.run_test(size=(60, 12)) as pilot:
        tabs = app.query_one("#tabs", Tabs)
        await pilot.pause()
        assert tabs.value == "team" and app.query_one("#t3").has_class("-active")
        await pilot.click("#t1")
        await pilot.pause()
        assert tabs.value == "account" and tabs.query(TabsContent).first().display
        with pytest.raises(ValueError):
            tabs.select("nope")


async def test_breadcrumb_separates_parts_with_chevrons_and_links_post_navigate():
    crumbs = Breadcrumb(
        BreadcrumbItem("Home", "home", id="h"),
        BreadcrumbEllipsis(),
        BreadcrumbItem("Docs", "docs", id="d"),
        BreadcrumbPage("Tabs", id="p"),
        id="b",
    )
    app = Recorder(crumbs)
    async with app.run_test(size=(60, 4)) as pilot:
        await pilot.pause()
        separators = crumbs.query(".breadcrumb-separator")
        assert len(separators) == 3
        assert all(s.render().plain == icon("chevron_right") for s in separators)
        assert app.query_one("#p").styles.text_style.bold and not app.query_one("#p").can_focus
        app.query_one("#h").focus()
        await pilot.pause()
        await pilot.press("right")
        assert app.focused.id == "d"
        await pilot.press("right")
        assert app.focused.id == "h"  # Wraps over links only.
        await pilot.press("enter")
        await pilot.click("#d")
        await pilot.pause()
        assert app.events == [("crumb", "home"), ("crumb", "docs")]


def test_page_window_keeps_the_ends_and_the_neighbours_and_fills_single_gaps():
    assert page_window(5, 10) == [1, None, 4, 5, 6, None, 10]
    assert page_window(1, 5) == [1, 2, None, 5]
    assert page_window(3, 5) == [1, 2, 3, 4, 5]
    assert page_window(1, 1) == [1]
    assert page_window(10, 10, neighbours=2) == [1, None, 8, 9, 10]


async def test_pagination_turns_pages_with_keys_and_clicks_and_stays_in_range():
    app = Recorder(Pagination(5, 10, id="p"))
    async with app.run_test(size=(60, 4)) as pilot:
        page = app.query_one("#p", Pagination)
        page.focus()
        await pilot.pause()
        assert page.render().plain.count(icon("chevron_left")) == 1
        await pilot.press("right", "pagedown")
        assert page.page == 7
        await pilot.press("left", "pageup", "left")
        assert page.page == 4
        await pilot.press("end")
        assert page.page == 10
        await pilot.press("right")  # Already last.
        assert page.page == 10 and app.events[-1] == ("page", 10)
        await pilot.press("home")
        assert page.page == 1
        # Click the "2": it is the number right after the first page and a space.
        text = page.render().plain
        await pilot.click("#p", offset=(1 + text.index("2"), 0))
        await pilot.pause()
        assert page.page == 2
        with pytest.raises(ValueError):
            Pagination(1, 0)


async def test_a_single_page_pagination_lets_the_arrows_through():
    app = Recorder(Pagination(1, 1, id="p"), Input(id="i"))
    async with app.run_test(size=(60, 6)) as pilot:
        app.query_one("#p").focus()
        await pilot.pause()
        await pilot.press("right")
        assert app.events == []


def make_collapsible(**kw):
    return Collapsible(
        CollapsibleTrigger("Details", key="ctrl+d", id="trig"),
        CollapsibleContent(Static("Hidden text", id="body")),
        id="col",
        **kw,
    )


async def test_collapsible_opens_and_closes_by_key_space_and_click_and_flips_the_chevron():
    app = Recorder(make_collapsible())
    async with app.run_test(size=(50, 8)) as pilot:
        section, trigger = app.query_one("#col", Collapsible), app.query_one("#trig")
        await pilot.pause()
        content = app.query_one(CollapsibleContent)
        assert not content.display
        assert trigger.render().plain.startswith(icon("chevron_right"))
        trigger.focus()
        await pilot.pause()
        await pilot.press("space")
        assert section.open and content.display
        assert trigger.render().plain.startswith(icon("chevron_down"))
        await pilot.press("ctrl+d")
        assert not section.open
        await pilot.click("#trig")
        await pilot.pause()
        assert section.open
        assert [e[2] for e in app.events] == [True, False, True]


def make_accordion(**kw):
    return Accordion(
        AccordionItem("One", Static("1"), value="one", id="a", open=True),
        AccordionItem("Two", Static("2"), value="two", id="b"),
        AccordionItem("Three", Static("3"), value="three", id="c", disabled=True),
        id="acc",
        **kw,
    )


async def test_single_accordion_opens_one_at_a_time_and_can_forbid_closing():
    app = Recorder(make_accordion())
    async with app.run_test(size=(50, 14)) as pilot:
        accordion = app.query_one("#acc", Accordion)
        await pilot.pause()
        assert accordion.value == ("one",)
        await pilot.click("#b CollapsibleTrigger")
        await pilot.pause()
        assert accordion.value == ("two",)
        await pilot.click("#b CollapsibleTrigger")
        await pilot.pause()
        assert accordion.value == ()  # Collapsible by default.
    app = Recorder(make_accordion(collapsible=False))
    async with app.run_test(size=(50, 14)) as pilot:
        accordion = app.query_one("#acc", Accordion)
        await pilot.pause()
        await pilot.click("#a CollapsibleTrigger")
        await pilot.pause()
        assert accordion.value == ("one",)  # The open item stays open.


async def test_multiple_accordion_keeps_several_open_and_arrows_skip_disabled_headings():
    app = Recorder(make_accordion(type="multiple"))
    async with app.run_test(size=(50, 14)) as pilot:
        accordion = app.query_one("#acc", Accordion)
        triggers = [t for t in accordion.query(CollapsibleTrigger)]
        triggers[0].focus()
        await pilot.pause()
        await pilot.press("down")
        assert app.focused is triggers[1]
        await pilot.press("space", "down")
        assert accordion.value == ("one", "two")
        assert app.focused is triggers[0]  # Wraps past the disabled third heading.
        await pilot.press("end")
        assert app.focused is triggers[1]
        await pilot.press("home")
        assert app.focused is triggers[0]
    with pytest.raises(ValueError):
        Accordion(type="triple")


def make_sidebar(**kw):
    return Sidebar(
        SidebarGroup(
            "Workspace",
            SidebarMenuItem("Home", "home", icon_name="home", id="home"),
            SidebarMenuItem("Search", "search", icon_name="search", id="search", key="ctrl+f"),
            SidebarMenuItem("Locked", "locked", icon_name="about", id="locked", disabled=True),
        ),
        id="side",
        **kw,
    )


async def test_sidebar_selects_by_enter_click_and_key_and_moves_with_the_arrows():
    app = Recorder(make_sidebar(value="home"))
    async with app.run_test(size=(40, 14)) as pilot:
        side = app.query_one("#side", Sidebar)
        await pilot.pause()
        assert app.query_one("#home").has_class("-active")
        app.query_one("#home").focus()
        await pilot.pause()
        await pilot.press("down")
        assert app.focused.id == "search"  # Skips the disabled item.
        await pilot.press("enter")
        assert side.value == "search" and app.query_one("#search").has_class("-active")
        assert not app.query_one("#home").has_class("-active")
        await pilot.press("home", "up")
        assert app.focused.id == "search"  # Wrapped to the last enabled item.
        await pilot.press("ctrl+f")
        await pilot.click("#home")
        await pilot.pause()
        assert app.events == [("sidebar", "search"), ("sidebar", "home")]


async def test_sidebar_folds_to_icons_with_ctrl_b_and_unfolds_again():
    app = Recorder(make_sidebar())
    async with app.run_test(size=(40, 14)) as pilot:
        side = app.query_one("#side", Sidebar)
        await pilot.pause()
        wide = side.region.width
        assert wide == 26 and "Home" in app.query_one("#home").render().plain
        assert app.query_one(".sidebar-label").display
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert side.collapsed and side.region.width == 5
        assert app.query_one("#home").render().plain == icon("home")
        assert not app.query_one(".sidebar-label").display
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert not side.collapsed and side.region.width == wide
        assert "Home" in app.query_one("#home").render().plain
