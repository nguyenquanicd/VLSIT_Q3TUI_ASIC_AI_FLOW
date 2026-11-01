"""Home: the brand, the input box, and the alerts (spec/tui.md "Home", "Alerts")."""

from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from q3tui.tui.alerts import AlertSpec, alerts, first_user_file
from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle
from q3tui.tui.ui.button import Button
from q3tui.tui.ui.prompt_box import PromptBox
from q3tui.tui.widgets.brand import WelcomeBrand

VARIANT = {"error": "destructive", "warning": "warning", "info": "default"}


class HomeAlert(Alert):
    """An Alert of Home: title, detail, and its action inside it, with a key (Alt+<n>)."""

    DEFAULT_CSS = """
    HomeAlert { margin-top: 1; }
    HomeAlert .alert-actions { height: 1; margin-top: 1; }
    """

    def __init__(self, spec: AlertSpec, key: str | None) -> None:
        parts = [AlertTitle(spec.title), AlertDescription(spec.detail)]
        if spec.action:
            parts.append(Horizontal(Button(spec.action, key=key, classes="alert-action"), classes="alert-actions"))
        super().__init__(*parts, variant=VARIANT[spec.severity])
        self.spec = spec

    @on(Button.Pressed, ".alert-action")
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.app.alert_action(self.spec.payload or "")


class HomeScreen(Screen):
    DEFAULT_CSS = """
    HomeScreen #home-body { width: 1fr; height: 1fr; margin: 1 0; }
    HomeScreen #welcome-stage { width: 1fr; height: auto; align: center top; padding: 1 3; }
    HomeScreen #welcome { width: 80; max-width: 100%; height: auto; }
    HomeScreen #home-file { width: 1fr; color: $text-muted; margin-bottom: 1; }
    HomeScreen PromptBox { margin-bottom: 1; }
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
        with VerticalScroll(id="home-body"), Container(id="welcome-stage"), Vertical(id="welcome"):
            yield WelcomeBrand(opened.flow.name or opened.config.config.pipeline.flow)
            if target:
                yield Static(f"Write {target}: what the design must do", id="home-file", markup=False)
                yield PromptBox()
            n = 0
            for spec in alerts(opened):
                key = None
                if spec.action and n < 9:
                    n += 1
                    key = f"alt+{n}"
                yield HomeAlert(spec, key)
        yield status

    def on_mount(self) -> None:
        self._fit(self.size.width)
        keys = [("enter", "write the file")] if self.query(PromptBox) else []
        self.app.set_keys([*keys, ("ctrl+r", "run"), ("ctrl+k", "commands"), ("alt+comma", "settings")])
        self.action_focus_prompt()

    def on_resize(self, event: events.Resize) -> None:
        self._fit(event.size.width)

    def _fit(self, width: int) -> None:
        for brand in self.query(WelcomeBrand):
            brand.set_class(width < 60, "narrow")

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
