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


async def test_a_refused_value_shows_under_the_field_and_keeps_the_file(tmp_path, home):
    from q3tui.tui.ui.field import FieldDescription, FieldError

    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        app.action_settings()
        await pilot.pause(1.0)
        row = next(r for r in app.screen.query("SettingRow") if r.key.dotted == "pipeline.max_fix_rounds"
                   and r.config_layer == "project")
        assert "fix loop" in str(row.query_one(FieldDescription).render())
        row.save("3")
        await pilot.pause(0.5)
        row = next(r for r in app.screen.query("SettingRow") if r.key.dotted == "pipeline.max_fix_rounds"
                   and r.config_layer == "project")
        value = row.query_one(".value")
        value.value = "99"
        value.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert str(row.query_one(FieldError).render()) and row.has_class("-invalid") and value.value == "99"
        assert "max_fix_rounds: 3" in (tmp_path / "proj/.q3tui/config.yaml").read_text()  # the file as it was
        await pilot.click(row.query_one(".row-key"))  # the name focuses the value
        assert app.screen.focused is value


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
        assert tabs in app.screen.focused.ancestors_with_self  # the focus stays in the tabs: Alt+<n> again works
        await pilot.press("alt+1")
        await pilot.pause(0.3)
        assert tabs.value == values[0]
        await pilot.press("alt+2")
        await pilot.pause(0.3)
        assert tabs.value == values[1]
        side = app.screen.query_one("#sidebar-tabs")
        row.focus()
        await pilot.pause(0.3)
        for n, want in ((1, "assistant"), (2, "flow"), (1, "assistant")):  # back and forth, from the input too
            await pilot.press(f"alt+{n}")
            await pilot.pause(0.5)
            assert side.value == want and side in app.screen.focused.ancestors_with_self
        app.action_settings()
        await pilot.pause(1.0)
        layers = app.screen.query_one("#layer-tabs")
        for n, want in ((3, "user"), (1, "session"), (2, "project")):
            await pilot.press(f"alt+{n}")
            await pilot.pause(0.5)
            assert layers.value == want and layers in app.screen.focused.ancestors_with_self


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


RUN = [
    {"kind": "run_started", "ts": "2026-11-01T09:45:42", "scope": {"only": "spec"}},
    {"kind": "stage_started", "ts": "2026-11-01T09:45:42", "stage": "s"},
    {"kind": "step_started", "ts": "2026-11-01T09:45:42", "step": "spec", "changes": {"first_run": True}},
    {"kind": "task_started", "ts": "2026-11-01T09:45:42", "step": "spec", "task": "spec", "model": "m"},
    {"kind": "tool_call", "ts": "2026-11-01T09:45:43", "step": "spec", "tool": "Read", "input": "spec/intent.md"},
    {"kind": "task_finished", "ts": "2026-11-01T09:45:51", "step": "spec", "task": "spec", "cost_usd": 0.12,
     "turns": 3},
    {"kind": "step_finished", "ts": "2026-11-01T09:45:51", "step": "spec", "result": "done", "cost_usd": 0.12},
    {"kind": "stage_finished", "ts": "2026-11-01T09:45:51", "stage": "s", "outcome": "waiting"},
    {"kind": "run_finished", "ts": "2026-11-01T09:45:51", "outcomes": {"s": "waiting"}, "cost_usd": 0.12},
]


async def test_a_step_is_one_line_with_its_llm_work_folded_under_it():
    from textual.app import App

    from q3tui.tui.ui.collapsible import CollapsibleContent
    from q3tui.tui.ui.marker import Marker
    from q3tui.tui.ui.trace import TraceCollapsible
    from q3tui.tui.widgets.activities import EventLine, EventLog

    class Live(App):
        def compose(self):
            yield EventLog(id="live")
            yield EventLog(RUN, id="past")

    app = Live()
    async with app.run_test(size=(100, 40)) as pilot:
        live = app.query_one("#live", EventLog)
        for e in RUN[:5]:
            await live.write(e)
        await pilot.pause()
        box = live.query_one(TraceCollapsible)
        assert box.open and box.query_one(EventLine).status == "running"  # open while it runs
        assert len(box.query_one(CollapsibleContent).query(EventLine)) == 2  # the task and its tool call
        for e in RUN[5:]:
            await live.write(e)
        await pilot.pause()
        line = box.query(EventLine).first()
        assert not box.open and line.status is None and "done" in line.description and "3 turns" in line.description
        assert len(live.query(TraceCollapsible)) == 1 and len(live.query(Marker)) == 2  # one line for the step
        past = app.query_one("#past", EventLog).query_one(TraceCollapsible)  # the Log tab: read back, closed
        assert not past.open and len(past.query_one(CollapsibleContent).query(EventLine)) == 3


async def test_home_collapses_a_multiline_paste(tmp_path, home):
    from textual import events

    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        box = app.screen.query_one("PromptInput")
        box.focus()
        await pilot.press(*"A ")
        pasted = "".join(f"line {i}\n" for i in range(12))
        app.post_message(events.Paste(pasted))
        await pilot.pause()
        assert box.text == "A [Pasted text #1 +12 lines]"
        assert box.value == "A " + pasted
        app.post_message(events.Paste("one line"))
        await pilot.pause()
        assert box.text.endswith("lines]one line")
        await pilot.press(*["backspace"] * 8, "backspace")
        assert box.text == "A "
        app.post_message(events.Paste("x\ny\n"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert (tmp_path / "proj/spec/intent.md").read_text() == "A x\ny\n"


async def test_a_paste_while_the_terminal_lost_focus_reaches_the_box(tmp_path, home):
    """A terminal's paste dialog takes the focus: the paste comes before the focus comes back."""
    from textual import events

    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        box = app.screen.query_one("PromptInput")
        box.focus()
        await pilot.pause()
        app.post_message(events.AppBlur())
        await pilot.pause()
        app.post_message(events.Paste("a\rb\rc\r"))
        await pilot.pause()
        assert box.value == "a\nb\nc\n"


async def test_a_click_on_a_widget_just_removed_does_not_crash(tmp_path, home):
    """Main rebuilds while a step runs: a click can land on a tab that was just removed."""
    from textual import events

    write(tmp_path / "proj/.q3tui/state/pipeline.json", "{}")
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        trigger = app.screen.query("TabsTrigger").last()
        x, y = trigger.region.offset
        parent = trigger.parent
        parent._nodes._remove(trigger)  # gone from the tree, still in the screen's map
        trigger._detach()
        app.post_message(events.MouseDown(None, x, y, 0, 0, 1, False, False, False,
                                          screen_x=x, screen_y=y))
        await pilot.pause()
        assert app.return_code is None
        parent._nodes._append(trigger)  # back, so that the app can shut down
        trigger._attach(parent)


async def test_the_log_keeps_what_you_opened_while_it_rebuilds(tmp_path, home):
    """Main rebuilds on each event of the step in view (a running step): an opened box stays open."""
    import json

    from q3tui.tui.ui.trace import TraceCollapsible

    write(tmp_path / "proj/.q3tui/state/pipeline.json", "{}")
    write(tmp_path / "proj/.q3tui/state/events.jsonl", "".join(json.dumps(e) + "\n" for e in RUN))
    app = app_for(tmp_path, home)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        main = app.screen.query_one(StepMain)
        await main.show("spec")
        main.query_one("#main-tabs").value = "log"
        await pilot.pause()
        box = main.query_one("#step-log").query_one(TraceCollapsible)
        assert not box.open
        box.set_open(True)
        await main.refresh_step()
        await pilot.pause()
        assert main.query_one("#main-tabs").value == "log"
        assert main.query_one("#step-log").query_one(TraceCollapsible).open
        await main.show("rtl")  # another step: its log starts closed
        await main.show("spec")
        assert not main.query_one("#step-log").query_one(TraceCollapsible).open


async def test_a_click_on_a_line_inside_a_run_does_not_close_the_run():
    from textual.app import App

    from q3tui.tui.ui.trace import TraceCollapsible
    from q3tui.tui.widgets.activities import EventLog

    class Live(App):
        def compose(self):
            yield EventLog(id="live")

    app = Live()
    async with app.run_test(size=(120, 30)) as pilot:
        log = app.query_one("#live", EventLog)
        for e in RUN[:4]:
            await log.write(e)
        await pilot.pause()
        box = log.query_one(TraceCollapsible)
        header, task = box.query("EventLine")[:2]
        assert box.open and task.parent is not box
        await pilot.click(task)
        await pilot.pause()
        assert box.open  # the task line heads nothing
        await pilot.click(header)
        await pilot.pause()
        assert not box.open
