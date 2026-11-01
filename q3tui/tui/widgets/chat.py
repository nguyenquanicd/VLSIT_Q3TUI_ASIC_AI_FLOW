"""The Assistant tab: the conversation, the cards that ask you, and the box you write in, with its `/` commands
(spec/tui.md "Keys in the Assistant tab", spec/assistant.md)."""

from __future__ import annotations

import asyncio
import shlex

from rich.markdown import Markdown as RichMarkdown
from textual import on
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.message import Message as TextualMessage
from textual.widget import Widget
from textual.widgets import Button, Static

from q3tui.assistant import Assistant, Tool
from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle
from q3tui.tui.ui.bubble import Bubble, BubbleContent
from q3tui.tui.ui.button import Button as Q3Button
from q3tui.tui.ui.command import Command, CommandItem
from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.input import Textarea
from q3tui.tui.ui.message_scroller import MessageScroller
from q3tui.tui.ui.questionnaire import Question, Questionnaire
from q3tui.tui.ui.text_button import TextButton


def parse_command(text: str) -> tuple[str, dict]:
    """`/name key=value …` → (name, {key: value})."""
    words = shlex.split(text[1:])
    if not words:
        return "", {}
    args = {}
    for w in words[1:]:
        k, sep, v = w.partition("=")
        if not sep:
            raise ValueError(f"`{w}`: write key=value")
        args[k] = {"true": True, "false": False}.get(v, v)
    return words[0], args


class ChatInput(Textarea):
    BINDINGS = [
        Binding("enter", "submit", "Send", priority=True),
        Binding("shift+enter", "line_break", "New line", priority=True),
        Binding("escape", "escape", "Stop", show=False),
        Binding("tab", "complete", "Complete", show=False),
    ]

    @property
    def panel(self) -> ChatPanel:
        return next(a for a in self.ancestors if isinstance(a, ChatPanel))

    def action_submit(self) -> None:
        panel = self.panel
        if panel.commands_open() and not panel.command_typed():
            panel.query_one(Command).choose_highlighted()
            return
        text = self.text.strip()
        if text:
            self.clear()
            panel.submit(text)

    def action_line_break(self) -> None:
        self.replace("\n", *self.selection)

    def action_escape(self) -> None:
        panel = self.panel
        if panel.commands_open():
            panel.query_one(Command).display = False
        elif panel.busy:
            panel.stop()
        else:
            raise SkipAction()

    def action_complete(self) -> None:
        panel = self.panel
        if panel.commands_open():
            panel.query_one(Command).choose_highlighted()
        else:
            self.screen.focus_next()

    def action_cursor_up(self, select: bool = False) -> None:
        if self.panel.commands_open() and not select:
            self.panel.query_one(Command).action_move(-1)
            return
        super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False) -> None:
        if self.panel.commands_open() and not select:
            self.panel.query_one(Command).action_move(1)
            return
        super().action_cursor_down(select)


class ConfirmCard(Vertical):
    """[Allow] [Decline]; y / n / Esc while the keyboard is on the card."""

    DEFAULT_CSS = """
    ConfirmCard { width: 1fr; height: auto; margin-bottom: 1; }
    ConfirmCard > .card-actions { height: 1; margin-top: 1; }
    ConfirmCard > .card-actions > Button { margin-right: 2; }
    """
    BINDINGS = [Binding("y", "answer(True)", show=False), Binding("n", "answer(False)", show=False),
                Binding("escape", "answer(False)", show=False)]

    def __init__(self, text: str, future: asyncio.Future) -> None:
        super().__init__()
        self.text, self.future = text, future

    def compose(self):
        yield Alert(AlertTitle(self.text), AlertDescription("The assistant asks for your OK."), variant="warning")
        with Horizontal(classes="card-actions"):
            yield Q3Button("Allow y", id="card-allow")
            yield Q3Button("Decline n", variant="secondary", id="card-decline")

    def on_mount(self) -> None:
        self.query_one("#card-allow").focus()

    @on(Q3Button.Pressed)
    def _pressed(self, event: Q3Button.Pressed) -> None:
        event.stop()
        self.action_answer(event.button.id == "card-allow")

    def action_answer(self, allowed: bool) -> None:
        if not self.future.done():
            self.future.set_result(allowed)
        self.remove()


class AskCard(Vertical):
    DEFAULT_CSS = "AskCard { width: 1fr; height: auto; padding: 0 1; background: $surface; margin-bottom: 1; }"
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, question: str, choices: list[str], future: asyncio.Future) -> None:
        super().__init__()
        self.question, self.choices, self.future = question, choices, future

    def compose(self):
        yield Questionnaire(Question("q", self.question, list(self.choices), freeform=True), keys="local")

    @on(Questionnaire.Submitted)
    def _submitted(self, event: Questionnaire.Submitted) -> None:
        event.stop()
        value = event.answers.get("q")
        if not self.future.done():
            self.future.set_result(", ".join(value) if isinstance(value, list) else str(value or ""))
        self.remove()

    def action_cancel(self) -> None:
        if not self.future.done():
            self.future.set_result(None)
        self.remove()


class ChatPanel(Vertical):
    """`ChatPanel(assistant_factory)`: the factory makes the Assistant with this panel as its host."""

    DEFAULT_CSS = """
    ChatPanel { height: 1fr; }
    ChatPanel #chat-head { height: 1; padding: 0 1; }
    ChatPanel #chat-status { width: 1fr; color: $text-muted; text-wrap: nowrap; text-overflow: ellipsis; }
    ChatPanel #chat-head TextButton { width: auto; margin-left: 1; }
    ChatPanel MessageScroller { height: 1fr; padding: 0 1; }
    ChatPanel .chat-you { margin: 1 0 0 0; }
    ChatPanel .chat-text { width: 1fr; height: auto; margin-top: 1; }
    ChatPanel .chat-tool { height: auto; color: $text-muted; }
    ChatPanel .chat-note { height: auto; color: $text-muted; }
    ChatPanel #chat-commands { margin: 0 1; height: auto; max-height: 10; }
    ChatPanel ChatInput { height: 4; margin: 0 1; }
    """

    class Context(TextualMessage):
        """Asks the screen what you are looking at: the screen fills `value`."""

    def __init__(self, ops, context, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.ops = ops
        self.context_fn = context  # () -> {step, tab, item}
        self.assistant = Assistant(ops, self, self.emit) if ops is not None else None
        self.busy = False
        self.worker = None

    def compose(self):
        with Horizontal(id="chat-head"):
            yield Static("", id="chat-status")
            yield TextButton("Stop", id="chat-stop", compact=True)
            yield TextButton(f"New chat {key_label('ctrl+l')}", id="chat-new", compact=True)
        yield MessageScroller(id="chat-log")
        yield Command(search=False, id="chat-commands")
        yield ChatInput(rows=2, placeholder="Ask the assistant, or / for a command…", id="chat-input")

    def on_mount(self) -> None:
        self.query_one(Command).display = False
        self.query_one(Command).set_entries(*self._command_items())

    # -- Host ---------------------------------------------------------------------------------------

    def context(self) -> dict:
        return self.context_fn()

    async def confirm(self, text: str) -> bool:
        future = asyncio.get_running_loop().create_future()
        await self.log_widget(ConfirmCard(text, future))
        return await future

    async def ask_user(self, question: str, choices: list[str]) -> str | None:
        future = asyncio.get_running_loop().create_future()
        await self.log_widget(AskCard(question, choices, future))
        return await future

    # -- the conversation ---------------------------------------------------------------------------

    async def log_widget(self, w: Widget) -> None:
        await self.query_one(MessageScroller).add(w)

    def emit(self, kind: str, data: dict) -> None:
        if kind == "text":
            self.call_later(self.log_widget, Static(RichMarkdown(data["text"]), classes="chat-text"))
        elif kind == "tool":
            args = data.get("input") or {}
            arg = next((str(args[k]) for k in ("file_path", "pattern", "step", "key", "id") if k in args), "")
            name = str(data["tool"]).removeprefix("mcp__q3tui__")
            self.call_later(self.log_widget, Static(Content.assemble((icon("tool"), "dim"), f" {name} ", (arg, "dim")),
                                                    classes="chat-tool"))
        elif kind == "done":
            self._status(f"${data.get('cost_usd', 0):,.3f}" + (f" · {data['error']}" if data.get("error") else ""))
        elif kind in ("error", "warning"):
            self.call_later(self.log_widget, Static(Content.styled(f"{icon(kind)} {data['message']}",
                                                                   "$text-error" if kind == "error" else "$text-warning"),
                                                    classes="chat-note"))
        elif kind == "stopped":
            self.call_later(self.log_widget, Static("stopped", classes="chat-note"))

    def _status(self, text: str) -> None:
        if self.is_mounted:
            self.query_one("#chat-status", Static).update(text)

    def submit(self, text: str) -> None:
        self.query_one(Command).display = False
        if text.startswith("/"):
            self.run_worker(self._command(text), exclusive=False)
            return
        if self.assistant is None:
            self.call_later(self.log_widget, Static("The flow has errors: the assistant is not available.",
                                                    classes="chat-note"))
            return
        if self.busy:
            return
        self.call_later(self.log_widget, Bubble(BubbleContent(text), variant="secondary", align="end",
                                                classes="chat-you"))
        self.worker = self.run_worker(self._ask(text), exclusive=True)

    async def _ask(self, text: str) -> None:
        self.busy = True
        self._status("thinking…")
        try:
            await self.assistant.ask(text)
        finally:
            self.busy = False

    async def _command(self, text: str) -> None:
        await self.log_widget(Static(Content.styled(text, "bold"), classes="chat-note"))
        try:
            name, args = parse_command(text)
            tools = self._tools()
            tool = next((t for t in tools if t.name == name), None)
            if tool is None:
                raise ValueError(f"no command `{name}` (type / for the list)")
            out = await tool.fn(args)
        except Exception as exc:  # noqa: BLE001 -- shown as a line of the chat
            out = f"{icon('error')} {exc}"
        await self.log_widget(Static(str(out), classes="chat-note", markup=False))

    def _tools(self) -> list[Tool]:
        if self.assistant is None:
            return []
        return self.assistant.tools(self.assistant.access(self.context().get("step")))

    def _command_items(self) -> list[CommandItem]:
        items = []
        for t in self._tools():
            if t.name in ("glob", "ask_user"):
                continue
            params = " ".join(f"{k}=…" for k in t.params)
            items.append(CommandItem(f"/{t.name}", f"/{t.name}", description=f"{params}  {t.description}"[:80],
                                     keywords=t.description))
        return items

    def stop(self) -> None:
        if self.assistant is not None:
            self.assistant.stop()
        if self.worker is not None:
            self.worker.cancel()
        self.busy = False
        self._status("stopped")

    def new_chat(self) -> None:
        if self.assistant is not None:
            self.assistant.new_chat()
        log = self.query_one(MessageScroller)
        for child in list(log.viewport.children):
            child.remove()
        self._status("new chat")

    # -- the command list ---------------------------------------------------------------------------

    def commands_open(self) -> bool:
        return self.query_one(Command).display

    def command_typed(self) -> bool:
        """The box holds a whole command (with a space): Enter runs it instead of picking from the list."""
        text = self.query_one(ChatInput).text
        return " " in text.strip() or text.strip() in {i.label for i in self._command_items()}

    @on(ChatInput.Changed, "#chat-input")
    def _typed(self, event) -> None:
        text = self.query_one(ChatInput).text
        command = self.query_one(Command)
        show = text.startswith("/") and "\n" not in text
        command.display = show
        if show:
            word = text[1:].split(" ", 1)[0].lower()
            command.set_entries(*[i for i in self._command_items() if word in i.label.lower()])

    @on(Command.Selected, "#chat-commands")
    def _chosen(self, event: Command.Selected) -> None:
        event.stop()
        box = self.query_one(ChatInput)
        box.text = f"{event.item.value} "
        box.move_cursor(box.document.end)
        self.query_one(Command).display = False
        box.focus()

    @on(Button.Pressed, "#chat-stop")
    def _stop_pressed(self, event) -> None:
        event.stop()
        self.stop()

    @on(Button.Pressed, "#chat-new")
    def _new_pressed(self, event) -> None:
        event.stop()
        self.new_chat()
