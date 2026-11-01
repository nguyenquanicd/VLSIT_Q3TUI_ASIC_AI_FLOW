import pytest
from textual.containers import Horizontal, Vertical

from q3tui.tui.ui.avatar import Avatar, AvatarGroup, initials
from q3tui.tui.ui.badge import Badge
from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.kbd import Kbd, KbdGroup
from q3tui.tui.ui.separator import Separator
from tests.ui.harness import Harness


async def test_kbd_draws_the_key_on_a_cap_and_groups_space_keys_apart():
    app = Harness(Kbd("ctrl+k", id="one"), KbdGroup("ctrl+k", "ctrl+b", id="group"))
    async with app.run_test(size=(60, 10)) as pilot:
        await pilot.pause()
        one = app.query_one("#one", Kbd)
        assert one.render().plain == key_label("ctrl+k")
        assert one.region.width == len(key_label("ctrl+k")) + 2  # One cell of padding each side.
        assert one.region.height == 1
        assert one.styles.padding.left == one.styles.padding.right == 1
        first, second = app.query_one("#group").query(Kbd)
        assert second.region.x == first.region.right + 1


@pytest.mark.parametrize(
    "variant", ["default", "secondary", "destructive", "outline", "success", "warning"]
)
async def test_badge_variants_differ_and_keep_one_row_with_text_padding(variant):
    app = Harness(Badge("New", variant=variant, id="badge"), Badge("Base", id="base"))
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        badge = app.query_one("#badge", Badge)
        assert badge.region.height == 1
        assert badge.region.width == len("New") + 2
        base = app.query_one("#base").background_colors[1]
        same = badge.background_colors[1] == base
        assert same is (variant == "default")


async def test_badge_icon_comes_before_the_label():
    app = Harness(Badge("Ready", icon_name="about", id="badge"))
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        assert app.query_one("#badge", Badge).render().plain == f"{icon('about')} Ready"


async def test_separators_span_their_container_in_one_cell():
    app = Harness(
        Vertical(Separator(id="h"), id="v1", classes="box"),
        Horizontal(Separator("vertical", id="v"), id="h1", classes="box"),
    )
    app.CSS = ".box { height: 5; width: 30; }"
    async with app.run_test(size=(60, 14)) as pilot:
        await pilot.pause()
        horizontal = app.query_one("#h")
        assert (horizontal.region.height, horizontal.region.width) == (1, 30)
        vertical = app.query_one("#v")
        assert (vertical.region.width, vertical.region.height) == (1, 5)
        with pytest.raises(ValueError):
            Separator("diagonal")


def test_initials_use_the_first_and_last_word():
    assert initials("Ada Lovelace") == "AL"
    assert initials("Ada Byron Lovelace") == "AL"
    assert initials("plato") == "PL"
    assert initials("  ") == "?"


async def test_avatar_color_depends_only_on_the_name():
    app = Harness(
        Avatar("Ada Lovelace", id="a1"), Avatar("Ada Lovelace", id="a2"), Avatar("Bo", id="b")
    )
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        one, two, other = (app.query_one(f"#{i}", Avatar) for i in ("a1", "a2", "b"))
        assert one.classes == two.classes
        assert one.render().plain == "AL" and one.region.width == 4
        assert any(c.startswith("-c") for c in other.classes)


async def test_avatar_group_lays_avatars_one_cell_apart():
    app = Harness(AvatarGroup("Ada Lovelace", "Bo Peep", "Cy", id="group"))
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        first, second, third = app.query_one("#group").query(Avatar)
        assert second.region.x == first.region.right + 1
        assert third.region.x == second.region.right + 1


async def test_spinner_cycles_its_glyphs_and_can_stop_and_start():
    from q3tui.tui.ui.spinner import Spinner

    app = Harness(Spinner("Loading", interval=0.02, id="spin"), Spinner(interval=0.02, id="bare"))
    async with app.run_test(size=(40, 6)) as pilot:
        spin = app.query_one("#spin", Spinner)
        await pilot.pause(0.25)
        assert spin.frame > 0
        assert spin.render().plain.endswith(" Loading")
        assert spin.render().plain[0] in {icon(f"spinner_{i}") for i in range(1, 7)}
        assert app.query_one("#bare").render().plain in {icon(f"spinner_{i}") for i in range(1, 7)}
        spin.stop()
        frozen = spin.frame
        await pilot.pause(0.15)
        assert spin.frame == frozen and not spin.running
        spin.start()
        await pilot.pause(0.15)
        assert spin.frame > frozen


async def test_skeleton_takes_its_size_and_pulses_between_two_colors():
    from q3tui.tui.ui.skeleton import Skeleton

    app = Harness(Skeleton(12, 2, interval=0.02, id="bar"), Skeleton(pulse=False, id="still"))
    async with app.run_test(size=(40, 8)) as pilot:
        bar = app.query_one("#bar", Skeleton)
        assert (bar.region.width, bar.region.height) == (12, 2)
        colors = {bar.background_colors[1]}
        for _ in range(6):
            await pilot.pause(0.03)
            colors.add(bar.background_colors[1])
        assert len(colors) == 2
        still = app.query_one("#still")
        before = still.background_colors[1]
        await pilot.pause(0.1)
        assert still.background_colors[1] == before


@pytest.mark.parametrize(
    ("value", "expected"), [(0, 0.0), (25, 0.25), (100, 1.0), (150, 1.0), (-5, 0.0)]
)
async def test_progress_fills_the_track_in_proportion(value, expected):
    from q3tui.tui.ui.progress import Progress

    app = Harness(Progress(value, label="Upload", id="p"))
    async with app.run_test(size=(60, 4)) as pilot:
        await pilot.pause()
        progress = app.query_one("#p", Progress)
        track = progress.query_one(".progress-track")
        fill = progress.query_one(".progress-fill")
        assert abs(fill.region.width - expected * track.region.width) <= 1
        assert progress.query_one(".progress-value").render().plain == f"{round(expected * 100)}%"
        assert progress.query_one(".progress-label").render().plain == "Upload"


async def test_progress_updates_when_the_value_changes_and_rejects_a_bad_total():
    from q3tui.tui.ui.progress import Progress

    app = Harness(Progress(0, 10, id="p"))
    async with app.run_test(size=(60, 4)) as pilot:
        await pilot.pause()
        progress = app.query_one("#p", Progress)
        progress.advance(5)
        await pilot.pause()
        assert progress.query_one(".progress-value").render().plain == "50%"
        progress.advance(50)  # Never past the total.
        await pilot.pause()
        assert progress.value == 10
        assert not progress.query_one(".progress-rest").display
    with pytest.raises(ValueError):
        Progress(1, 0)


async def test_indeterminate_progress_slides_a_block_and_shows_no_percentage():
    from q3tui.tui.ui.progress import Progress

    app = Harness(Progress(indeterminate=True, id="p"))
    async with app.run_test(size=(60, 4)) as pilot:
        progress = app.query_one("#p", Progress)
        await pilot.pause(0.05)
        first = progress.query_one(".progress-fill").region.x
        await pilot.pause(0.5)
        assert progress.query_one(".progress-fill").region.x != first
        assert not progress.query(".progress-value")
