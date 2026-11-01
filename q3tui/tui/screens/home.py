"""Home: the brand, the input box, and the alerts (spec/tui.md "Home", "Alerts")."""

from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from q3tui.tui.alerts import AlertSpec, alerts, first_user_file
from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle
from q3tui.tui.ui.prompt_box import PromptBox
from q3tui.tui.widgets.brand import WelcomeBrand

VARIANT = {"error": "destructive", "warning": "warning", "info": "default"}


class HomeAlert(Alert):
    """An Alert of Home. Clicking it (or Enter on it in the list) does its action: opens the settings or a dialog."""

    DEFAULT_CSS = """
    HomeAlert { margin-top: 0; }
    HomeAlert.-actionable:hover { background: $panel; }
    HomeAlert.-selected { background: $panel; }
    """

    def __init__(self, spec: AlertSpec) -> None:
        super().__init__(AlertTitle(spec.title), AlertDescription(spec.detail), variant=VARIANT[spec.severity])
        self.spec = spec
        self.set_class(bool(spec.action), "-actionable")
        if spec.action:
            self.tooltip = f"Click or Enter: {spec.action.lower()}"

    def on_click(self, event: events.Click) -> None:
        event.stop()
        alerts = self.parent
        if isinstance(alerts, AlertList):
            alerts.select(list(alerts.query(HomeAlert)).index(self))
        self.act()

    def act(self) -> None:
        if self.spec.action:
            self.app.alert_action(self.spec.payload or "")


class AlertList(Vertical, can_focus=True):
    """The alerts of Home: Up / Down choose one, Enter does its action (Tab comes here from the input box)."""

    DEFAULT_CSS = """
    AlertList { height: auto; margin-top: 1; }
    AlertList:focus { background: transparent; }
    """
    BINDINGS = [Binding("up", "move(-1)", show=False), Binding("down", "move(1)", show=False),
                Binding("enter", "act", show=False)]

    def __init__(self, *alerts: HomeAlert) -> None:
        super().__init__(*alerts)
        self.index = 0

    @property
    def items(self) -> list[HomeAlert]:
        return list(self.query(HomeAlert))

    def select(self, index: int) -> None:
        items = self.items
        if not items:
            return
        self.index = index % len(items)
        for n, item in enumerate(items):
            item.set_class(n == self.index and self.has_focus, "-selected")
        items[self.index].scroll_visible(animate=False)

    def on_focus(self) -> None:
        self.select(self.index)

    def on_blur(self) -> None:
        for item in self.items:
            item.remove_class("-selected")

    def action_move(self, step: int) -> None:
        self.select(self.index + step)

    def action_act(self) -> None:
        items = self.items
        if items:
            items[self.index].act()


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
            specs = alerts(opened)
            if specs:
                yield AlertList(*(HomeAlert(spec) for spec in specs))
        yield status

    def on_mount(self) -> None:
        self._fit(self.size.width)
        self.action_focus_prompt()
        self.app.refresh_keys()

    def on_descendant_focus(self) -> None:
        self.app.refresh_keys()

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
