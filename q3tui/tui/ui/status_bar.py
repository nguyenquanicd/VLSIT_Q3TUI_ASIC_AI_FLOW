from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; padding: 0 2;
        background: $surface; color: $text-muted; }
    """

    def __init__(self) -> None:
        super().__init__("● ready", id="status-bar")
