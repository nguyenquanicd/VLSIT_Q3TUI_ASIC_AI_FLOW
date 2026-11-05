"""API keys of the LLM providers (docs/spec/config.md "Providers").

Kept in `$Q3TUI_HOME/keys.env` (default `~/.q3tui/keys.env`, mode 600): one per machine and user, never in a project's
q3tui.yaml, which is shared with the project. An environment variable of the same name wins over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

# the keys the settings dialog and `q3tui keys` know: name → what it is for
KNOWN = {
    "ANTHROPIC_API_KEY": "Claude API key (llm.provider: claude_api)",
    "OPENAI_API_KEY": "OpenAI API key (llm.provider: openai_api)",
}


def home() -> Path:
    return Path(os.environ.get("Q3TUI_HOME") or "~/.q3tui").expanduser()


def path() -> Path:
    return home() / "keys.env"


def read() -> dict[str, str]:
    """The keys in the file (NAME=value lines; # comments and blank lines skipped)."""
    p = path()
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        out[name.strip()] = value.strip().strip('"').strip("'")
    return out


def get(name: str) -> str | None:
    """The key: the environment variable, else the file's; None when neither has it."""
    return os.environ.get(name) or read().get(name) or None


def is_set(name: str) -> bool:
    return bool(get(name))


def _write(values: dict[str, str]) -> Path:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "# Q3TUI provider keys (q3tui keys set / the settings dialog's Provider tab). Keep this file private.\n"
    text += "".join(f"{k}={v}\n" for k, v in sorted(values.items()))
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return p


def set_key(name: str, value: str) -> Path:
    """Save one key (the file is created mode 600)."""
    if not name or not name.replace("_", "").isalnum():
        raise ValueError(f"not a key name: {name!r}")
    value = value.strip()
    if not value:
        raise ValueError(f"{name}: empty key")
    values = read()
    values[name] = value
    return _write(values)


def clear(name: str) -> bool:
    """Remove one key from the file; False when it was not there."""
    values = read()
    if name not in values:
        return False
    del values[name]
    _write(values)
    return True
