"""The Codex CLI backend (llm.backend: codex) against tests/fake_codex.py, a stand-in for `codex exec --json`."""

import json
from pathlib import Path

import anyio
import pytest
from pydantic import BaseModel

from q3tui.core.config import Config
from q3tui.core.events import EventBus
from q3tui.llm import runtime
from q3tui.llm.codex import runner
from q3tui.llm.codex.bridge import ToolBridge
from q3tui.llm.runtime import Stage, StageError
from q3tui.llm.tooldef import tool

FAKE = str(Path(__file__).parent / "fake_codex.py")


class Out(BaseModel):
    title: str
    n: int = 3
    tags: list[str] = []


def cfg(**codex) -> Config:
    return Config.model_validate({"llm": {"backend": "codex", "codex": {
        "bin": FAKE, "prices": {"*": {"input": 2.0, "cached_input": 0.5, "output": 10.0}}, **codex}}})


def go(stage, config, monkeypatch, plan, tmp_path):
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FAKE_CODEX_PLAN", json.dumps(plan))
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    res = anyio.run(lambda: runtime.run_stage(stage, config, bus.scoped("t")))
    runs = [json.loads(line) for line in log.read_text().splitlines()]
    return res, runs, events


def test_strict_schema_and_prune():
    schema = runtime.output_schema(Out)
    strict = runner.strict_schema(schema)
    assert strict["required"] == ["title", "n", "tags"] and strict["additionalProperties"] is False
    assert strict["properties"]["n"]["type"] == ["integer", "null"] and strict["properties"]["title"]["type"] == "string"
    assert runner.prune_nulls({"title": "x", "n": None, "tags": None}, schema) == {"title": "x"}


def test_command_line():
    opts = runner.CodexOptions(model="gpt-x", effort="high", system_prompt="", cwd=Path("."), tools=[], schema=None, resume="abc",
                               extra_args=["--profile", "q3"])
    cmd = runner.command(opts, "http://127.0.0.1:1/mcp", Path("s.json"))
    assert cmd[:4] == ["codex", "exec", "--json", "--skip-git-repo-check"] and cmd[-3:] == ["resume", "abc", "-"]
    assert ["-m", "gpt-x"] == cmd[4:6] and "--output-schema" in cmd and "--profile" in cmd
    joined = " ".join(cmd)
    assert 'model_reasoning_effort="high"' in joined and "features.shell_tool=false" in joined and 'approval_policy="never"' in joined


def test_structured_result_cost_and_files(monkeypatch, tmp_path):
    st = Stage(name="t", system_prompt="SYS", prompt="go", cwd=tmp_path, output_model=Out)
    res, runs, events = go(st, cfg(effort="medium"), monkeypatch, {"reply": json.dumps({"title": "x", "n": None, "tags": None})}, tmp_path)
    assert res.output == Out(title="x") and res.session_id == "thread-1"
    # 600 fresh input · 400 cached · 200 output tokens at 2 / 0.5 / 10 USD per million
    assert res.cost_usd == pytest.approx((600 * 2.0 + 400 * 0.5 + 200 * 10.0) / 1e6)
    argv = runs[0]["argv"]
    assert "--output-schema" in argv and 'model_reasoning_effort="medium"' in argv
    assert runs[0]["prompt"].startswith("SYS") and "go" in runs[0]["prompt"]
    kinds = {e.kind for e in events}
    assert {"llm_text", "llm_done", "sdk"} <= kinds


def test_resume_sends_no_system_prompt_and_asks_for_a_json_block(monkeypatch, tmp_path):
    st = Stage(name="t", system_prompt="SYS", prompt="again", cwd=tmp_path, output_model=Out, resume="thread-9")
    res, runs, _ = go(st, cfg(), monkeypatch, {"reply": '```json\n{"title": "y"}\n```'}, tmp_path)
    assert res.output.title == "y"
    argv = runs[0]["argv"]
    assert argv[-3:] == ["resume", "thread-9", "-"] and "--output-schema" not in argv
    assert "SYS" not in runs[0]["prompt"] and "```json" in runs[0]["prompt"]


def test_invalid_output_is_asked_again_in_the_same_session(monkeypatch, tmp_path):
    st = Stage(name="t", system_prompt="SYS", prompt="go", cwd=tmp_path, output_model=Out)
    monkeypatch.setenv("FAKE_CODEX_PLAN", json.dumps({"reply": json.dumps({"n": 1})}))
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "log.jsonl"))
    with pytest.raises(StageError) as exc:
        anyio.run(lambda: runtime.run_stage(st, cfg(), EventBus().scoped("t")))
    assert "title" in str(exc.value)
    runs = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert len(runs) == 3 and runs[1]["argv"][-3:-1] == ["resume", "thread-1"] and "title" in runs[1]["prompt"]


def test_a_failed_turn_is_a_stage_error(monkeypatch, tmp_path):
    st = Stage(name="t", system_prompt="SYS", prompt="go", cwd=tmp_path)
    with pytest.raises(StageError, match="quota exceeded"):
        go(st, cfg(), monkeypatch, {"fail": "quota exceeded"}, tmp_path)


def test_a_missing_binary_says_how_to_install_it(tmp_path):
    st = Stage(name="t", system_prompt="SYS", prompt="go", cwd=tmp_path)
    with pytest.raises(StageError, match="was not found"):
        anyio.run(lambda: runtime.run_stage(st, cfg(bin="no-such-codex-binary"), EventBus().scoped("t")))


def test_q3tui_tools_and_confined_files_over_the_bridge(monkeypatch, tmp_path):
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "a.md").write_text("hello\nworld\n")
    (tmp_path / "src" / "tb").mkdir(parents=True)
    (tmp_path / "src" / "tb" / "secret.sv").write_text("module tb;")
    calls = []

    @tool("design_summary", "summary", {})
    async def design_summary(args: dict) -> dict:
        calls.append(args)
        return {"content": [{"type": "text", "text": "top=fifo"}]}

    st = Stage(name="t", system_prompt="SYS", prompt="go", cwd=tmp_path, builtin_tools=["Read", "Grep", "Glob", "Write"],
               sdk_tools=[design_summary], deny_dirs=[tmp_path / "src" / "tb"], write_files=[tmp_path / "out.md"])
    plan = {"calls": [["design_summary", {}], ["read_file", {"file_path": "spec/a.md"}],
                      ["read_file", {"file_path": "src/tb/secret.sv"}], ["grep", {"pattern": "wor", "path": "spec"}],
                      ["write_file", {"file_path": "spec/a.md", "content": "x"}], ["write_file", {"file_path": "out.md", "content": "ok"}]]}
    _, runs, _ = go(st, cfg(), monkeypatch, plan, tmp_path)
    listed, summary, read, denied, grep, bad_write, good_write = runs[0]["tool_results"]
    assert {t["name"] for t in listed["result"]["tools"]} == {"design_summary", "read_file", "grep", "glob", "write_file"}
    assert calls == [{}] and summary["result"]["content"][0]["text"] == "top=fifo"
    assert "hello" in read["result"]["content"][0]["text"]
    assert denied["result"]["isError"] and "not accessible" in denied["result"]["content"][0]["text"]
    assert "spec/a.md:2:world" in grep["result"]["content"][0]["text"].replace("\\", "/") and "secret" not in grep["result"]["content"][0]["text"]
    assert bad_write["result"]["isError"] and (tmp_path / "spec" / "a.md").read_text() == "hello\nworld\n"
    assert not good_write["result"].get("isError") and (tmp_path / "out.md").read_text() == "ok"


def test_the_endpoint_needs_the_token(tmp_path):
    import urllib.error
    import urllib.request

    async def main():
        async with ToolBridge([]) as bridge:
            def call(auth):
                req = urllib.request.Request(bridge.url, b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
                                             {"Authorization": auth, "Content-Type": "application/json"})
                return urllib.request.urlopen(req).status

            assert await anyio.to_thread.run_sync(call, f"Bearer {bridge.token}") == 200
            with pytest.raises(urllib.error.HTTPError) as exc:
                await anyio.to_thread.run_sync(call, "Bearer wrong")
            assert exc.value.code == 401

    anyio.run(main)
