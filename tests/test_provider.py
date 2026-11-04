"""llm.provider: where the stages' requests go (llm/provider.py), the provider keys (core/keys.py), the LiteLLM gateway's
config (llm/gateway.py). No gateway is started and no LLM is called."""

import json
import os
import stat

import pytest

from q3tui.core import keys
from q3tui.core.config import Config, uses_effort
from q3tui.core.ops import Ops
from q3tui.core.project import Project
from q3tui.llm import gateway, provider, runtime
from q3tui.llm.runtime import Stage, StageError, build_options
from q3tui.pipeline.engine import Engine
from tests.fakes import FakeLLM, use_test_flow


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Keys and the gateway's files in a temporary Q3TUI home; no key from the developer's environment."""
    h = tmp_path / "q3home"
    monkeypatch.setenv("Q3TUI_HOME", str(h))
    for name in keys.KNOWN:
        monkeypatch.delenv(name, raising=False)
    return h


def _cfg(**llm) -> Config:
    return Config.model_validate({"llm": llm})


def test_keys_are_private_and_the_environment_wins(home, monkeypatch):
    assert keys.get("OPENAI_API_KEY") is None and not keys.is_set("OPENAI_API_KEY")
    p = keys.set_key("OPENAI_API_KEY", "  sk-file  ")
    assert p == home / "keys.env" and stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert keys.get("OPENAI_API_KEY") == "sk-file"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert keys.get("OPENAI_API_KEY") == "sk-env"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert keys.clear("OPENAI_API_KEY") and not keys.clear("OPENAI_API_KEY") and keys.get("OPENAI_API_KEY") is None
    with pytest.raises(ValueError):
        keys.set_key("OPENAI_API_KEY", " ")
    with pytest.raises(ValueError):
        keys.set_key("BAD NAME", "x")


def test_effort_is_for_claude_models_only():
    assert uses_effort("claude-sonnet-5-5") and not uses_effort("claude-haiku-4-5")
    assert not uses_effort("gpt-5.3-codex")
    llm = _cfg(model="gpt-5.3-codex", effort="high").llm.for_stage(None, "x")
    assert llm.effort is None


def test_claude_subscription_sets_nothing():
    assert provider.stage_env(_cfg(), "claude-sonnet-5-5") == {}


def test_claude_api_needs_its_key_and_takes_the_api_base():
    cfg = _cfg(provider="claude_api", api_base="https://claude.example/v1")
    with pytest.raises(provider.ProviderError, match="ANTHROPIC_API_KEY"):
        provider.stage_env(cfg, "claude-sonnet-5-5")
    keys.set_key("ANTHROPIC_API_KEY", "sk-ant")
    env = provider.stage_env(cfg, "claude-sonnet-5-5")
    assert env == {"ANTHROPIC_API_KEY": "sk-ant", "ANTHROPIC_BASE_URL": "https://claude.example/v1"}
    other = provider.stage_env(cfg, "kimi-k3")  # another model behind a Claude-compatible endpoint: it serves the small calls too
    assert other["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "kimi-k3" and other["ANTHROPIC_SMALL_FAST_MODEL"] == "kimi-k3"


def test_openai_providers_go_through_the_gateway(monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "ensure", lambda p, base: calls.append((p, base)) or "http://127.0.0.1:4555")
    env = provider.stage_env(_cfg(provider="openai", model="gpt-5.3-codex"), "gpt-5.3-codex")
    assert calls == [("openai", None)]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4555"
    assert env["ANTHROPIC_AUTH_TOKEN"] == env["ANTHROPIC_API_KEY"] == gateway.token()
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "gpt-5.3-codex"
    assert stat.S_IMODE(os.stat(gateway.home() / "token").st_mode) == 0o600


def test_gateway_config_and_what_each_provider_needs():
    sub = json.loads(gateway.config_text("openai", None).split("\n", 1)[1])
    assert sub["model_list"] == [{"model_name": "*", "litellm_params": {"model": "chatgpt/*"}}]
    assert sub["litellm_settings"]["drop_params"] is True
    assert sub["general_settings"]["master_key"] == "os.environ/Q3TUI_GATEWAY_KEY"
    api = json.loads(gateway.config_text("openai_api", "http://vllm:8000/v1").split("\n", 1)[1])
    assert api["model_list"][0]["litellm_params"] == {"model": "openai/*", "api_base": "http://vllm:8000/v1",
                                                      "api_key": "os.environ/OPENAI_API_KEY"}
    assert "api.openai.com" in gateway.config_text("openai_api", None)
    with pytest.raises(gateway.GatewayError, match="ChatGPT login"):
        gateway.check("openai")
    (gateway.chatgpt_dir()).mkdir(parents=True)
    (gateway.chatgpt_dir() / "auth.json").write_text("{}")
    gateway.check("openai")
    with pytest.raises(gateway.GatewayError, match="OPENAI_API_KEY"):
        gateway.check("openai_api")
    keys.set_key("OPENAI_API_KEY", "sk-oa")
    gateway.check("openai_api")
    assert gateway.env()["OPENAI_API_KEY"] == "sk-oa" and gateway.env()["CHATGPT_TOKEN_DIR"] == str(gateway.chatgpt_dir())
    with pytest.raises(gateway.GatewayError):
        gateway.config_text("claude", None)


def test_stage_options_for_another_providers_model(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "ensure", lambda p, base: "http://127.0.0.1:4555")
    cfg = _cfg(provider="openai", model="gpt-5.5", effort="high", thinking_budget=6000)
    opts = build_options(Stage(name="s", system_prompt="s", prompt="p", cwd=tmp_path), cfg)
    assert opts.model == "gpt-5.5" and opts.effort is None and opts.thinking is None
    assert opts.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4555" and opts.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    cfg.llm.env = {"ANTHROPIC_BASE_URL": "http://mine"}  # llm.env still wins
    assert build_options(Stage(name="s", system_prompt="s", prompt="p", cwd=tmp_path), cfg).env["ANTHROPIC_BASE_URL"] == "http://mine"
    # a provider that cannot serve: the stage fails with what is missing
    with pytest.raises(StageError, match="ANTHROPIC_API_KEY"):
        build_options(Stage(name="s", system_prompt="s", prompt="p", cwd=tmp_path), _cfg(provider="claude_api"))


@pytest.fixture
def ops(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "run_stage", FakeLLM())
    use_test_flow(tmp_path)
    return Ops(Engine(Project.open(tmp_path)))


def test_provider_settings_keys_never_reach_q3tui_yaml(ops, home):
    cfg = ops.project.cfg
    vals = ops.settings()
    assert vals["llm.provider"] == "claude" and vals["keys.OPENAI_API_KEY"] is None
    msg = ops.apply_settings({"llm.provider": "openai_api", "llm.api_base": "http://vllm:8000/v1",
                              "keys.OPENAI_API_KEY": "sk-secret-1"}, save=True)
    assert cfg.llm.provider == "openai_api" and cfg.llm.api_base == "http://vllm:8000/v1"
    assert cfg.llm.model == provider.MODEL_HINTS["openai_api"][0] and cfg.llm.effort is None  # the Claude model left behind
    assert keys.get("OPENAI_API_KEY") == "sk-secret-1" and "OPENAI_API_KEY" in msg
    saved = (ops.project.root / "q3tui.yaml").read_text()
    assert "sk-secret-1" not in saved and "keys" not in saved and "openai_api" in saved
    assert ops.settings()["keys.OPENAI_API_KEY"] is None                       # never read back
    assert "saved OPENAI_API_KEY" in ops.apply_settings({"keys.OPENAI_API_KEY": "sk-secret-2"})
    assert ops.apply_settings({"keys.OPENAI_API_KEY": ""}) == "settings unchanged" and keys.get("OPENAI_API_KEY") == "sk-secret-2"
    ops.apply_settings({"llm.provider": "claude"})                              # back: a Claude model again
    assert cfg.llm.model == Config().llm.model and cfg.llm.effort == Config().llm.effort
    assert "gateway not running" in ops.gateway("status")


async def test_provider_tab_in_the_settings_dialog(tmp_path, monkeypatch, home):
    from textual.widgets import Button, Input, Select

    from q3tui.tui.app import Q3TUIApp
    from q3tui.tui.screens import SettingsScreen

    monkeypatch.setattr(runtime, "run_stage", FakeLLM())
    use_test_flow(tmp_path)
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "intent.md").write_text("A two-stage FIFO\n")
    app = Q3TUIApp(Project.open(tmp_path))
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.press("comma")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        key = screen.query_one("#set-keys-OPENAI_API_KEY", Input)
        assert key.password and key.value == "" and "not set" in key.placeholder
        assert screen.query_one("#chatgpt-login", Button)
        screen.query_one("#set-llm-provider", Select).value = "openai_api"
        key.value = "sk-typed"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert app.project.cfg.llm.provider == "openai_api" and keys.get("OPENAI_API_KEY") == "sk-typed"
        assert "sk-typed" not in (tmp_path / "q3tui.yaml").read_text()
        await pilot.press("comma")
        await pilot.pause()
        assert "✔ set" in app.screen.query_one("#set-keys-OPENAI_API_KEY", Input).placeholder


def test_the_installer_prepares_the_same_gateway():
    from pathlib import Path

    assert "q3tui gateway install" in (Path(__file__).parent.parent / "install.sh").read_text()


def test_litellm_has_one_environment_made_once(monkeypatch):
    import subprocess

    ran = []

    def fake_run(cmd, **kw):
        ran.append(cmd[:3])
        if cmd[1] == "venv":
            py = gateway._venv_python()
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(gateway, "_uv", lambda: "uv")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert not gateway.installed()
    said = []
    py = gateway.install(said.append)
    assert py == gateway.venv() / "bin" / "python" and gateway.installed() and said[-1] == "LiteLLM installed"
    assert ran == [["uv", "venv", "--quiet"], ["uv", "pip", "install"]]
    assert gateway.python_cmd("-c", "x") == [str(py), "-c", "x"] and len(ran) == 2        # used as it is: no install again
    assert gateway.login_cmd()[0] == str(py)
    (gateway.venv() / ".q3tui-litellm").write_text("litellm[proxy]>=1.0\n")             # another requirement: made again
    assert not gateway.installed()


async def test_the_chatgpt_login_runs_once_and_can_be_cancelled(tmp_path, monkeypatch):
    import sys

    from textual.widgets import Button, Static

    from q3tui.tui.app import Q3TUIApp

    monkeypatch.setattr(runtime, "run_stage", FakeLLM())
    monkeypatch.setattr(gateway, "install", lambda log=None: None)
    monkeypatch.setattr(gateway, "login_cmd", lambda: [sys.executable, "-u", "-c",
                                                        "import time; print('1) Visit https://x 2) Enter code: AB-12', flush=True); time.sleep(60)"])
    use_test_flow(tmp_path)
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "intent.md").write_text("A two-stage FIFO\n")
    app = Q3TUIApp(Project.open(tmp_path))
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.press("comma")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#chatgpt-login", Button).press()
        for _ in range(100):
            await pilot.pause(0.05)
            if "Enter code" in str(screen.query_one("#chatgpt-login-out", Static).render()):
                break
        assert "Enter code: AB-12" in str(screen.query_one("#chatgpt-login-out", Static).render())
        assert str(screen.query_one("#chatgpt-login", Button).label) == "Cancel login"
        proc = screen._login_proc
        screen.query_one("#chatgpt-login", Button).press()          # the same button cancels it
        for _ in range(100):
            await pilot.pause(0.05)
            if screen._login_proc is None:
                break
        assert proc.returncode is not None and "login cancelled" in str(screen.query_one("#chatgpt-login-out", Static).render())
        assert str(screen.query_one("#chatgpt-login", Button).label) == "Log in to ChatGPT"
