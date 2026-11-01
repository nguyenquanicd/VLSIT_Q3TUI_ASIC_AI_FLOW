"""spec/tui.md: the screens driven with Textual's Pilot, on a small flow with step code and no LLM."""

from pathlib import Path

import pytest

from q3tui.runtime.session import open_project
from q3tui.tui.app import Q3App
from q3tui.tui.screens.home import HomeAlert, HomeScreen
from q3tui.tui.screens.settings import SettingsScreen
from q3tui.tui.screens.workspace import WorkspaceScreen
from q3tui.tui.widgets.flow_tree import FlowRow
from q3tui.tui.widgets.main import StepMain

WRITE = '''
class Step:
    async def run(self, ctx):
        for name, path in ctx.outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<!-- section: intro -->\\nhello\\n<!-- section: ports -->\\nclk\\n")
'''


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    write(h / "flows/f/FLOW.md", "---\nname: f\ndescription: d\nversion: 1.0.0\nstages: [s]\n---\n")
    write(h / "stages/s/STAGE.md", "---\nname: s\ndescription: d\nversion: 1.0.0\nsteps: [spec, rtl]\n---\n")
    write(h / "steps/spec/STEP.md", "---\nname: spec\ndescription: writes the spec\nversion: 1.0.0\ngate: manual\n"
          "inputs:\n  - {artifact: intent, path: spec/intent.md}\noutputs:\n"
          "  - {artifact: spec, path: spec/spec.md, view: {kind: sections, review: true}}\n---\n")
    write(h / "steps/spec/step.py", WRITE)
    write(h / "steps/rtl/STEP.md", "---\nname: rtl\ndescription: writes the RTL\nversion: 1.0.0\ntools:\n  - {role: sim}\n"
          "inputs:\n  - {artifact: spec}\noutputs:\n  - {artifact: rtl, path: src/top.sv}\n---\n")
    write(h / "steps/rtl/step.py", WRITE)
    write(h / "config.yaml", "pipeline: {flow: f}\n")
    return h


def app_for(tmp_path, home) -> Q3App:
    return Q3App(open_project(tmp_path / "proj", home=home), home=home)


async def test_home_then_workspace(tmp_path, home):
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        titles = [a.spec.title for a in app.screen.query(HomeAlert)]
        assert any("sim" in t for t in titles)  # the missing tool role, with [Open settings]
        app.screen.action_focus_prompt()
        await pilot.press(*"a FIFO")
        await pilot.press("enter")
        await pilot.pause()
        assert (tmp_path / "proj/spec/intent.md").read_text() == "a FIFO\n"
        assert isinstance(app.screen, WorkspaceScreen)


async def test_run_approve_and_review(tmp_path, home):
    write(tmp_path / "proj/spec/intent.md", "x")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        app.start_run(only="spec")
        await app.workers.wait_for_complete()
        await pilot.pause(0.5)
        screen = app.screen
        assert isinstance(screen, WorkspaceScreen)
        row = next(r for r in screen.query(FlowRow) if r.ident == "spec")
        assert row.status.display == "approval waiting"
        row.focus()
        await pilot.press("enter")
        await pilot.pause()
        main = screen.query_one(StepMain)
        assert main.step == "spec" and main.query("#do-approve")
        await pilot.press("C")  # confirm every review item
        await pilot.press("a")
        await pilot.pause()
        assert app.opened.ops.status("spec").display == "approved"


async def test_settings_writes_the_project_file(tmp_path, home):
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        app.action_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        row = next(r for r in app.screen.query("SettingRow") if r.key.dotted == "pipeline.max_fix_rounds"
                   and r.config_layer == "project")
        row.save("3")
        await pilot.pause()
        assert "max_fix_rounds: 3" in (tmp_path / "proj/.q3tui/config.yaml").read_text()
        assert app.opened.config.config.pipeline.max_fix_rounds == 3


async def test_chat_command(tmp_path, home):
    write(tmp_path / "proj/spec/intent.md", "x")
    write(tmp_path / "proj/.q3tui/state/pipeline.json", "{}")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, WorkspaceScreen)
        await pilot.press("alt+1")
        await pilot.press(*"/status")
        await pilot.press("enter")  # takes the command from the list
        await pilot.press("enter")  # runs it
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = " ".join(str(w.render()) for w in screen.query(".chat-note"))
        assert "spec (s): pending" in text


async def test_palette_and_shortcuts(tmp_path, home):
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        assert type(app.screen).__name__ == "ShortcutsDialog"
        await pilot.press("escape")
        await pilot.press("ctrl+k")
        await pilot.pause()
        assert type(app.screen).__name__ == "CommandDialog"


async def test_f8_opens_the_cost(tmp_path, home):
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("f8")
        await pilot.pause()
        assert type(app.screen).__name__ == "CostDialog"
        await pilot.press("escape")
        await pilot.pause()
        assert type(app.screen).__name__ == "HomeScreen"


async def test_home_shows_the_existing_intent(tmp_path, home):
    write(tmp_path / "proj/spec/intent.md", "a FIFO\n")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        box = app.screen.query_one("PromptInput")
        assert box.text == "a FIFO"
        await pilot.press("end", *" of 16")
        await pilot.press("enter")
        await pilot.pause()
        assert (tmp_path / "proj/spec/intent.md").read_text() == "a FIFO of 16\n"


async def test_global_alt_keys_work_while_typing(tmp_path, home):
    from textual import events

    write(tmp_path / "proj/.q3tui/state/pipeline.json", "{}")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("alt+1")
        await pilot.pause()
        assert type(app.focused).__name__ == "ChatInput"
        # what the terminal parser makes of ESC 2: the key alt+2 carrying the character "2"
        app.post_message(events.Key("alt+2", "2"))
        await pilot.pause(0.3)
        assert app.screen.query_one("#sidebar-tabs").value == "flow"
        assert app.screen.query_one("#chat-input").text == ""  # the digit was not typed


async def test_alt_number_picks_a_tab_of_the_tabs_around_the_focus(tmp_path, home):
    write(tmp_path / "proj/spec/intent.md", "x")
    write(tmp_path / "proj/.q3tui/state/pipeline.json", "{}")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(0.5)
        app.start_run(only="spec")
        await app.workers.wait_for_complete()
        await pilot.pause(0.5)
        row = next(r for r in app.screen.query(FlowRow) if r.ident == "spec")
        row.focus()
        await pilot.press("enter", "tab")  # the step in Main, then the focus in Main
        await pilot.pause(0.3)
        tabs = app.screen.query_one("#main-tabs")
        values = [t.value for t in tabs.triggers]
        await pilot.press("alt+2")
        await pilot.pause(0.3)
        assert tabs.value == values[1]
        app.action_settings()
        await pilot.pause(1.0)
        await pilot.press("alt+3")
        await pilot.pause(0.5)
        assert app.screen.query_one("#layer-tabs").value == "user"


async def test_row_menu_is_a_context_menu_with_the_gate_in_effect(tmp_path, home):
    from q3tui.tui.widgets.flow_tree import RowMenu

    write(tmp_path / "proj/spec/intent.md", "x")
    write(tmp_path / "proj/.q3tui/state/pipeline.json", "{}")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(0.5)
        row = next(r for r in app.screen.query(FlowRow) if r.ident == "spec")
        row.focus()
        await pilot.press("shift+f10")
        menu = app.screen.query_one(RowMenu)
        for _ in range(20):
            await pilot.pause(0.05)
            if menu.active_popup is not None:
                break
        popup = menu.active_popup
        assert popup is not None and popup.region.y == row.region.bottom
        gate = next(c for c in menu.menus[0].content.children if hasattr(c, "trigger") and c.trigger.label == "Gate")
        assert gate.content.children[0].value == "gate-step:spec:manual"  # the gate in effect is marked
        await pilot.press("escape")
        await pilot.pause()
        assert menu.active_popup is None and app.screen.focused is row
        await pilot.click(row, button=3)
        for _ in range(20):
            await pilot.pause(0.05)
            if menu.active_popup is not None:
                break
        assert menu.active_popup is not None
        await pilot.press("enter")  # Run only
        await pilot.pause()
        assert menu.active_popup is None
