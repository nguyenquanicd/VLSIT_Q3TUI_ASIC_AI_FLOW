"""Home: the brand, the input box, and the alerts (spec/tui.md "Home")."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from q3tui.tui.alerts import AlertSpec, alerts, first_user_file
from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle
from q3tui.tui.ui.button import Button
from q3tui.tui.ui.prompt_box import PromptBox

BRAND = r"""
 ██████╗ ██████╗ ████████╗██╗   ██╗██╗
██╔═══██╗╚════██╗╚══██╔══╝██║   ██║██║
██║   ██║ █████╔╝   ██║   ██║   ██║██║
██║▄▄ ██║ ╚═══██╗   ██║   ██║   ██║██║
╚██████╔╝██████╔╝   ██║   ╚██████╔╝██║
 ╚══▀▀═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝
"""
VARIANT = {"error": "destructive", "warning": "warning", "info": "default"}


class HomeAlert(Horizontal):
    DEFAULT_CSS = """
    HomeAlert { height: auto; margin-bottom: 1; }
    HomeAlert > Alert { width: 1fr; }
    HomeAlert > Button { margin-left: 1; }
    """

    def __init__(self, spec: AlertSpec) -> None:
        super().__init__()
        self.spec = spec

    def compose(self) -> ComposeResult:
        yield Alert(AlertTitle(self.spec.title), AlertDescription(self.spec.detail), variant=VARIANT[self.spec.severity])
        if self.spec.action:
            yield Button(self.spec.action, id="alert-action")

    @on(Button.Pressed, "#alert-action")
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.app.alert_action(self.spec.payload or "")


class HomeScreen(Screen):
    DEFAULT_CSS = """
    HomeScreen #home-body { padding: 1 2; }
    HomeScreen #brand { width: auto; color: $primary; }
    HomeScreen #home-input { width: 80; max-width: 100%; height: auto; margin: 1 0; }
    HomeScreen #home-file { color: $text-muted; width: auto; }
    HomeScreen #home-alerts { width: 100; max-width: 100%; height: auto; }
    """
    BINDINGS = [Binding("alt+p", "focus_prompt", show=False)]

    def __init__(self, bars) -> None:
        super().__init__()
        self.bars = bars

    def compose(self) -> ComposeResult:
        opened = self.app.opened
        title, status = self.bars()
        yield title
        target = first_user_file(opened)
        with VerticalScroll(id="home-body"):
            yield Center(Static(BRAND, id="brand", markup=False))
            if target:
                yield Center(Static(f"Write {target}: what the design must do", id="home-file", markup=False))
                yield Center(Vertical(PromptBox(), id="home-input"))
            with Center(), Vertical(id="home-alerts"):
                for spec in alerts(opened):
                    yield HomeAlert(spec)
        yield status

    def on_mount(self) -> None:
        self.app.set_keys([("enter", "write the file"), ("ctrl+r", "run"), ("ctrl+k", "commands")])

    def action_focus_prompt(self) -> None:
        boxes = self.query(PromptBox)
        if boxes:
            boxes.first().focus_input()

    @on(PromptBox.Submitted)
    def _submitted(self, event: PromptBox.Submitted) -> None:
        event.stop()
        target = first_user_file(self.app.opened)
        if target:
            self.app.write_user_file(target, event.text)
