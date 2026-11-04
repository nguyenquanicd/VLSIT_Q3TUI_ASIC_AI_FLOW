"""The LiteLLM gateway for the OpenAI providers (docs/spec/config.md "Providers").

The Claude Agent SDK speaks Anthropic's Messages API. For `llm.provider: openai` (a ChatGPT subscription, the Codex
models) and `openai_api` (the OpenAI API or any endpoint that speaks it), Q3TUI runs a LiteLLM proxy on 127.0.0.1 that
takes those requests and forwards them to the provider; every stage's SDK is pointed at it (`provider.stage_env`).

LiteLLM runs in its own virtual environment, `$Q3TUI_HOME/gateway/venv` (its proxy pins a `rich` older than Textual's),
made once with uv (`q3tui gateway install`, run by install.sh, or on first use) and used directly afterwards. One gateway
per machine and user, under `$Q3TUI_HOME/gateway/`: `config.yaml` (written from the project's provider settings),
`state.json` (pid, port, the config it serves), `token` (the proxy's key, mode 600), `chatgpt/` (the ChatGPT login),
`gateway.log`. It keeps running between Q3TUI runs; a
project with other provider settings restarts it with its own config. `q3tui gateway stop` stops it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from q3tui.core import keys

LITELLM = "litellm[proxy]>=1.108"  # what `install` puts into the gateway's own environment
OPENAI_API_BASE = "https://api.openai.com/v1"
START_TIMEOUT_S = 240  # LiteLLM's import is slow on a network home
HEALTH_TTL_S = 30.0  # a gateway found healthy is not checked again for this long
_healthy: dict[str, float] = {}  # config hash → when it was last found healthy


class GatewayError(RuntimeError):
    """The gateway cannot serve: LiteLLM or uv missing, a key or the login missing, it did not start."""


def home() -> Path:
    return keys.home() / "gateway"


def chatgpt_dir() -> Path:
    return home() / "chatgpt"


def logged_in() -> bool:
    """A ChatGPT login is saved (`q3tui gateway login`); LiteLLM refreshes its token by itself."""
    return (chatgpt_dir() / "auth.json").is_file()


def uses_gateway(provider: str) -> bool:
    return provider in ("openai", "openai_api")


def _uv() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise GatewayError("the gateway's LiteLLM is installed with uv, and uv was not found on PATH (https://docs.astral.sh/uv/)")
    return uv


def venv() -> Path:
    return home() / "venv"


def _venv_python() -> Path:
    return venv() / "bin" / "python"


def installed() -> bool:
    """LiteLLM's environment exists and was made for this requirement (a changed LITELLM makes it again)."""
    marker = venv() / ".q3tui-litellm"
    return _venv_python().is_file() and marker.is_file() and marker.read_text().strip() == LITELLM


def install(log=None) -> Path:
    """Make LiteLLM's environment (once: a few minutes); `log(line)` is told what happens. Returns its python."""
    if installed():
        return _venv_python()
    home().mkdir(parents=True, exist_ok=True)
    import fcntl

    with open(home() / ".install.lock", "w") as lock:  # (its own lock: ensure() holds the start lock while it installs)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if installed():
            return _venv_python()
        uv = _uv()
        say = log or (lambda line: None)
        say(f"installing LiteLLM into {venv()} (once; a few minutes)")
        for cmd in ([uv, "venv", "--quiet", "--clear", "--python", ">=3.12", str(venv())],
                    [uv, "pip", "install", "--quiet", "--compile-bytecode", "--python", str(_venv_python()), LITELLM]):
            done = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if done.returncode:
                raise GatewayError(f"installing LiteLLM failed: {' '.join(cmd[:3])}: "
                                   f"{(done.stderr or done.stdout).strip()[-600:]}")
        (venv() / ".q3tui-litellm").write_text(LITELLM + "\n")
        say("LiteLLM installed")
    return _venv_python()


def python_cmd(*args: str) -> list[str]:
    """`python <args>` in LiteLLM's environment (made first when it is missing)."""
    return [str(install()), *args]


def login_cmd() -> list[str]:
    """The ChatGPT device-code login: prints a link and a code, waits until they were entered, saves the token."""
    return python_cmd("-u", "-c", "print('loading LiteLLM…', flush=True); "
                                  "from litellm.llms.chatgpt.authenticator import Authenticator; "
                                  "Authenticator().get_access_token(); print('ChatGPT login saved')")


def env() -> dict[str, str]:
    """What the LiteLLM processes need besides the caller's environment."""
    out = {"CHATGPT_TOKEN_DIR": str(chatgpt_dir()), "Q3TUI_GATEWAY_KEY": token()}
    for name in keys.KNOWN:
        value = keys.get(name)
        if value:
            out[name] = value
    return out


def token() -> str:
    """The proxy's key (generated once, mode 600): only Q3TUI's own stages hold it."""
    p = home() / "token"
    if p.is_file() and p.read_text().strip():
        return p.read_text().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    value = "sk-q3tui-" + secrets.token_hex(16)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    return value


def config_text(provider: str, api_base: str | None) -> str:
    """LiteLLM's config: every model name goes to the provider (the name as the provider has it, e.g. gpt-5.3-codex)."""
    if provider == "openai":
        params = {"model": "chatgpt/*"}
    elif provider == "openai_api":
        params = {"model": "openai/*", "api_base": api_base or OPENAI_API_BASE, "api_key": "os.environ/OPENAI_API_KEY"}
    else:
        raise GatewayError(f"provider '{provider}' does not use the gateway")
    cfg = {
        "model_list": [{"model_name": "*", "litellm_params": params}],
        # the SDK sends Claude's own parameters (thinking, effort, cache control): dropped where the provider has none
        "litellm_settings": {"drop_params": True},
        "general_settings": {"master_key": "os.environ/Q3TUI_GATEWAY_KEY"},
    }
    return "# written by Q3TUI (q3tui/llm/gateway.py) from llm.provider / llm.api_base; rewritten on every start\n" + json.dumps(cfg, indent=2) + "\n"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _state() -> dict:
    try:
        return json.loads((home() / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _health(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/liveliness", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def _free_port(preferred: int = 4000) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise GatewayError("no free port for the gateway")


@contextlib.contextmanager
def _lock():
    """One start at a time: several Q3TUI runs (lanes, other flows) may need the gateway at once."""
    import fcntl

    home().mkdir(parents=True, exist_ok=True)
    with open(home() / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def check(provider: str) -> None:
    """What the provider needs before the gateway can serve it; GatewayError says what is missing."""
    if provider == "openai" and not logged_in():
        raise GatewayError("llm.provider is openai (a ChatGPT subscription) and there is no ChatGPT login yet: "
                           "`q3tui gateway login`, or the Provider tab of the settings (,)")
    if provider == "openai_api" and not keys.is_set("OPENAI_API_KEY"):
        raise GatewayError("llm.provider is openai_api and OPENAI_API_KEY is not set: `q3tui keys set OPENAI_API_KEY`, "
                           "or the Provider tab of the settings (,)")


def ensure(provider: str, api_base: str | None) -> str:
    """The gateway's URL for this provider, started (or restarted with this config) when needed."""
    text = config_text(provider, api_base)
    h = _hash(text + json.dumps(sorted(env().items())))  # a changed key restarts it too
    st = _state()
    if st.get("hash") == h and time.monotonic() - _healthy.get(h, -1e9) < HEALTH_TTL_S:
        return f"http://127.0.0.1:{st['port']}"
    check(provider)
    with _lock():
        st = _state()
        if st.get("hash") == h and _alive(st.get("pid")) and _health(st["port"]):
            _healthy[h] = time.monotonic()
            return f"http://127.0.0.1:{st['port']}"
        stop()
        cfg_path = home() / "config.yaml"
        cfg_path.write_text(text)
        port = _free_port()
        log = open(home() / "gateway.log", "ab")
        proc = subprocess.Popen(python_cmd("-m", "litellm.proxy.proxy_cli", "--config", str(cfg_path), "--host", "127.0.0.1",
                                           "--port", str(port)),
                                env={**os.environ, **env()}, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True, cwd=home())
        (home() / "state.json").write_text(json.dumps({"pid": proc.pid, "port": port, "hash": h, "provider": provider,
                                                      "api_base": api_base, "started": time.time()}))
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise GatewayError(f"the gateway exited at start (code {proc.returncode}); see {home() / 'gateway.log'}")
            if _health(port):
                _healthy[h] = time.monotonic()
                return f"http://127.0.0.1:{port}"
            time.sleep(1.0)
        stop()
        raise GatewayError(f"the gateway did not answer within {START_TIMEOUT_S} s; see {home() / 'gateway.log'}")


def stop() -> bool:
    """Stop the running gateway; False when none ran."""
    st = _state()
    pid = st.get("pid")
    _healthy.clear()
    with contextlib.suppress(OSError):
        (home() / "state.json").unlink()
    if not _alive(pid):
        return False
    with contextlib.suppress(OSError):
        os.killpg(pid, signal.SIGTERM)
    for _ in range(50):
        if not _alive(pid):
            return True
        time.sleep(0.1)
    with contextlib.suppress(OSError):
        os.killpg(pid, signal.SIGKILL)
    return True


def status() -> dict:
    """{running, url, provider, api_base, pid, chatgpt_login, keys}."""
    st = _state()
    running = _alive(st.get("pid")) and bool(st.get("port")) and _health(st["port"])
    return {"running": running, "url": f"http://127.0.0.1:{st['port']}" if running else None,
            "provider": st.get("provider") if running else None, "api_base": st.get("api_base") if running else None,
            "pid": st.get("pid") if running else None, "chatgpt_login": logged_in(),
            "keys": {name: keys.is_set(name) for name in keys.KNOWN}}
