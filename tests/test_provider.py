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
from q3tui.llm import gateway, models, provider, runtime
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
    monkeypatch.setattr(models, "_litellm_map", LITELLM_MAP)  # LiteLLM's model data, as the tests need it
    return h


LITELLM_MAP = {
    "chatgpt/gpt-5.5": {"mode": "responses", "supports_reasoning": True, "supports_xhigh_reasoning_effort": True},
    "chatgpt/gpt-6-sol": {"mode": "responses", "supports_reasoning": True, "supports_xhigh_reasoning_effort": True},
    "chatgpt/gpt-5.1-codex-mini": {"mode": "responses", "supports_reasoning": True},
    "chatgpt/gpt-image-2": {"mode": "image_generation"},
    "gpt-5.5": {"mode": "chat", "supports_reasoning": True, "supports_xhigh_reasoning_effort": True},
    "gpt-4o": {"mode": "chat"},
    "claude-sonnet-5-5": {"mode": "chat", "supports_reasoning": True},
}


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


def test_the_efforts_each_model_takes():
    assert models.efforts_for("claude", "claude-sonnet-5-5")[0] == models.EFFORTS
    assert models.efforts_for("claude", "claude-haiku-4-5")[0] == ()
    assert models.efforts_for("openai", "gpt-5.5") == (("low", "medium", "high", "xhigh"), "")
    assert models.efforts_for("openai", "gpt-5.1-codex-mini")[0] == ("low", "medium", "high")
    assert models.efforts_for("openai_api", "gpt-4o")[0] == ()                      # does not reason
    levels, note = models.efforts_for("openai_api", "my-local-llm")                  # unknown: the usual levels, said so
    assert levels == ("low", "medium", "high") and "not in LiteLLM" in note
    assert models.fit_effort("max", ("low", "medium", "high", "xhigh")) == "xhigh"
    assert models.fit_effort("xhigh", ("low", "medium", "high")) == "high"
    assert models.fit_effort("medium", ("low", "medium", "high")) == "medium"
    assert models.fit_effort("high", ()) is None and models.fit_effort(None, ("low",)) is None
    assert uses_effort("claude-sonnet-5-5") and not uses_effort("claude-haiku-4-5")
    assert uses_effort("gpt-5.5", "openai") and not uses_effort("gpt-4o", "openai_api")
    assert _cfg(provider="openai", model="gpt-5.5", effort="max").llm.for_stage(None, "x").effort == "xhigh"
    assert _cfg(provider="openai_api", model="gpt-4o", effort="high").llm.for_stage(None, "x").effort is None


def test_the_models_each_provider_lists(monkeypatch, home):
    assert models.list_models("claude") == (list(models.CLAUDE_MODELS), "")
    found, note = models.list_models("openai")                                     # LiteLLM's chatgpt/* chat models
    assert [m for m, _ in found] == ["gpt-6-sol", "gpt-5.5", "gpt-5.1-codex-mini"] and note == ""
    calls = []

    def fake_get(url, headers):
        calls.append((url, headers))
        if "anthropic" in url or "claude.example" in url:
            return {"data": [{"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"}]}
        return {"data": [{"id": "gpt-5.5"}, {"id": "text-embedding-3-small"}, {"id": "qwen3-coder"}, {"id": "tts-1"}]}

    monkeypatch.setattr(models, "_get_json", fake_get)
    found, note = models.list_models("openai_api", "http://vllm:8000/v1")         # no key: suggestions, said so
    assert "OPENAI_API_KEY" in note and calls == []
    keys.set_key("OPENAI_API_KEY", "sk-oa")
    found, note = models.list_models("openai_api", "http://vllm:8000/v1/")
    assert [m for m, _ in found] == ["gpt-5.5", "qwen3-coder"] and note == ""     # embeddings / tts left out
    assert calls[-1] == ("http://vllm:8000/v1/models", {"authorization": "Bearer sk-oa"})
    models.list_models("openai_api", "http://vllm:8000/v1/")                       # cached: not asked again
    assert len(calls) == 1
    models.list_models("openai_api", "http://vllm:8000/v1/", refresh=True)
    assert len(calls) == 2
    keys.set_key("ANTHROPIC_API_KEY", "sk-ant")
    found, _ = models.list_models("claude_api", "https://claude.example")
    assert found == [("claude-opus-5-5", "Claude Opus 5.5")]
    assert calls[-1][0] == "https://claude.example/v1/models?limit=1000" and calls[-1][1]["x-api-key"] == "sk-ant"

    def down(url, headers):
        raise OSError("connection refused")

    monkeypatch.setattr(models, "_get_json", down)
    found, note = models.list_models("openai_api", "http://other:1/v1")            # unreachable: suggestions, never an error
    assert found and "connection refused" in note


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
    (gateway.chatgpt_dir() / "auth.json").write_text('{"device_code_requested_at": 1.0}')   # a code asked for: no login yet
    assert not gateway.logged_in()
    with pytest.raises(gateway.GatewayError, match="ChatGPT login"):
        gateway.check("openai")
    gateway.clear_pending_login()                                     # the next login shows a new code at once
    assert json.loads((gateway.chatgpt_dir() / "auth.json").read_text()) == {}
    (gateway.chatgpt_dir() / "auth.json").write_text('{"access_token": "t", "refresh_token": "r", "device_code_requested_at": 1.0}')
    assert gateway.logged_in()
    gateway.clear_pending_login()                                     # a saved login is left alone
    assert "device_code_requested_at" in json.loads((gateway.chatgpt_dir() / "auth.json").read_text())
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
    assert opts.model == "gpt-5.5" and opts.effort == "high" and opts.thinking is None   # the gateway maps it to reasoning_effort
    cfg.llm.effort = "max"
    assert build_options(Stage(name="s", system_prompt="s", prompt="p", cwd=tmp_path), cfg).effort == "xhigh"   # its highest
    cfg.llm.effort = "high"
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
    assert cfg.llm.model == provider.MODEL_HINTS["openai_api"][0] and cfg.llm.effort == "high"  # the Claude model left behind
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


async def test_the_chatgpt_login_has_its_own_dialog_and_can_be_cancelled(tmp_path, monkeypatch):
    import sys

    from textual.widgets import Button, Static

    from q3tui.tui.app import Q3TUIApp
    from q3tui.tui.screens import LoginScreen, SettingsScreen

    monkeypatch.setattr(runtime, "run_stage", FakeLLM())
    monkeypatch.setattr(gateway, "install", lambda log=None: None)
    monkeypatch.setattr(gateway, "login_cmd", lambda: [sys.executable, "-u", "-c",
                                                        "import time; print('loading LiteLLM…'); print('Sign in with ChatGPT using device code:');"
                                                        "print('1) Visit https://auth.openai.com/codex/device'); print('2) Enter code: AB12-CD34', "
                                                        "flush=True); time.sleep(60)"])
    use_test_flow(tmp_path)
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "intent.md").write_text("A two-stage FIFO\n")
    app = Q3TUIApp(Project.open(tmp_path))
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.press("comma")
        await pilot.pause()
        app.screen.query_one("#chatgpt-login", Button).press()
        await pilot.pause()
        login = app.screen
        assert isinstance(login, LoginScreen)
        for _ in range(100):
            await pilot.pause(0.05)
            if login.code:
                break
        assert login.link == "https://auth.openai.com/codex/device" and login.code == "AB12-CD34"
        assert "AB12-CD34" in str(login.query_one("#login-code", Static).render())
        assert not login.query_one("#login-copy-code", Button).disabled
        proc = login.proc
        login.query_one("#login-cancel", Button).press()             # cancel: the login process stops, back to the settings
        await pilot.pause()
        for _ in range(100):
            if proc.returncode is not None:
                break
            await pilot.pause(0.05)
        assert proc.returncode is not None and isinstance(app.screen, SettingsScreen)
        assert "not logged in" in str(app.screen.query_one("#chatgpt-login-out", Static).render())


async def test_the_dialog_lists_the_providers_models_and_each_models_efforts(tmp_path, monkeypatch):
    from textual.widgets import Select

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

        def options(wid):
            return [v for _, v in screen.query_one(f"#{wid}", Select)._options]

        async def settle():
            for _ in range(40):
                await pilot.pause(0.05)
                if not any(w.is_running for w in screen.workers):
                    return

        await settle()
        assert "claude-sonnet-5-5" in options("set-llm-model")
        screen.query_one("#set-llm-provider", Select).value = "openai"            # another provider: its models
        await settle()
        assert [v for v in options("set-llm-model") if v.startswith("gpt")] == ["gpt-6-sol", "gpt-5.5", "gpt-5.1-codex-mini"]
        assert screen.query_one("#set-llm-model", Select).value == "gpt-6-sol"     # the Claude model left behind
        assert [v for v in options("set-llm-effort") if v != "__none__"] == ["low", "medium", "high", "xhigh"]
        screen.query_one("#set-llm-effort", Select).value = "xhigh"
        screen.query_one("#set-llm-model", Select).value = "gpt-5.1-codex-mini"   # a model without xhigh: its highest
        await settle()
        assert screen.query_one("#set-llm-effort", Select).value == "high"
        assert "Models: 3 from openai" in str(screen.query_one("#provider-models-note").render())
        await pilot.press("ctrl+s")
        await pilot.pause()
        cfg = app.project.cfg.llm
        assert (cfg.provider, cfg.model, cfg.effort) == ("openai", "gpt-5.1-codex-mini", "high")
