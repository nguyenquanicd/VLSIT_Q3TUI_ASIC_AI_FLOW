"""spec/assistant.md: the flow part of its prompt, its tools and confirmations, what it may read and write, its
session and cost — with a fake LLM."""

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from q3tui.assistant import Assistant, flow_part, run_tool
from q3tui.engine import EngineError
from q3tui.llm import runtime as llm
from q3tui.runtime.session import open_project
from tests.test_tui import home, write  # noqa: F401 -- the fixture


class FakeHost:
    def __init__(self, allow=True, step=None):
        self.allow, self.step, self.asked = allow, step, []

    async def confirm(self, text):
        self.asked.append(text)
        return self.allow

    async def ask_user(self, question, choices):
        return choices[0] if choices else None

    def context(self):
        return {"step": self.step}


def assistant(tmp_path, home, **host):  # noqa: F811
    opened = open_project(tmp_path / "proj", home=home)
    events = []
    a = Assistant(opened.ops, FakeHost(**host), lambda k, d: events.append((k, d)))
    return opened, a, events


def test_flow_part(tmp_path, home):  # noqa: F811
    opened, _, _ = assistant(tmp_path, home)
    text = flow_part(opened.flow)
    assert "Step `spec`: writes the spec" in text and "`spec` → `spec/spec.md`" in text
    assert "your file spec/intent.md" in text


async def test_confirmations(tmp_path, home):  # noqa: F811
    _, a, _ = assistant(tmp_path, home, allow=False, step="spec")
    tools = a.tools(a.access("spec"))
    with pytest.raises(EngineError, match="declined"):
        await run_tool(tools, "reset", {"step": "spec"})
    with pytest.raises(EngineError, match="declined"):
        await run_tool(tools, "set_gate_mode", {"mode": "unattended"})
    with pytest.raises(EngineError, match="declined"):
        await run_tool(tools, "request_change", {"step": "rtl", "text": "x"})  # not the step in view
    assert "set" in await run_tool(tools, "set_gate_mode", {"mode": "manual"})  # manual needs no OK
    assert "spec (s): missing_input" in await run_tool(tools, "status", {})
    assert len(a.host.asked) == 3


def test_access_follows_the_step_in_view(tmp_path, home):  # noqa: F811
    _, a, _ = assistant(tmp_path, home)
    over = a.access(None)
    assert over.check("Read", {"file_path": "anything.txt"}) is None
    assert over.check("Write", {"file_path": "spec/spec.md"}) is not None
    spec = a.access("spec")
    assert spec.check("Write", {"file_path": "spec/spec.md"}) is None
    assert spec.check("Write", {"file_path": "spec/intent.md"}) is None  # a user file the step reads
    assert spec.check("Read", {"file_path": "src/top.sv"}) is not None
    assert spec.check("Read", {"file_path": ".q3tui/state/pipeline.json"}) is not None


async def test_ask_records_session_and_cost(tmp_path, home, monkeypatch):  # noqa: F811
    calls = []

    def fake(*, prompt, options):
        calls.append((prompt, options))

        async def gen():
            yield AssistantMessage([TextBlock("Done.")], "m")
            yield ResultMessage("success", 1, 1, False, 1, "as-1", total_cost_usd=0.05 * len(calls))

        return gen()

    monkeypatch.setattr(llm, "query", fake)
    opened, a, events = assistant(tmp_path, home, step="spec")
    await a.ask("what is next?")
    await a.ask("and then?")
    assert calls[0][0].startswith("[TUI context] step: spec\n[Q3TUI] This task may read")
    assert calls[0][1].resume is None and calls[1][1].resume == "as-1"
    assert ("text", {"text": "Done."}) in events
    assert opened.ops.cost()["assistant_usd"] == pytest.approx(0.10)
    a.new_chat()
    await a.ask("again")
    assert calls[2][1].resume is None
