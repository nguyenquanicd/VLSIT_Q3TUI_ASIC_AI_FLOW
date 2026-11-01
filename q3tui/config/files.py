"""Writing the config files (user and project layers), keeping their comments, key order and layout.

A file is never left unreadable: the text is read back before it replaces the file.
"""

from __future__ import annotations

import io
from pathlib import Path

from q3tui.config.layers import ConfigError
from q3tui.config.schema import INSTALLED_KEYS, Config


def _yaml():
    from ruamel.yaml import YAML

    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _load(path: Path):
    from ruamel.yaml.comments import CommentedMap

    if not path.is_file() or not path.read_text().strip():
        return CommentedMap()
    data = _yaml().load(path.read_text())
    if data is None:
        return CommentedMap()
    if not isinstance(data, dict):
        raise ConfigError("the top level must be a mapping", path, 1)
    return data


def _save(path: Path, data) -> None:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    text = buf.getvalue()
    try:
        _yaml().load(text)
    except Exception as exc:
        raise ConfigError(f"not written: the result would not read back ({exc})", path) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def set_value(path: Path, dotted: str, value) -> None:
    """Set one key of a config file (creating the file and the maps on the way)."""
    from ruamel.yaml.comments import CommentedMap

    data = _load(path)
    parts = dotted.split(".")
    node = data
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = CommentedMap()
        node = node[p]
    node[parts[-1]] = value
    _save(path, data)


def unset_value(path: Path, dotted: str) -> bool:
    """Remove one key of a config file, so that the lower layer shows through again (not `null`).
    True when it was there."""
    data = _load(path)
    parts = dotted.split(".")
    node = data
    for p in parts[:-1]:
        node = node.get(p) if isinstance(node, dict) else None
        if node is None:
            return False
    if not isinstance(node, dict) or parts[-1] not in node:
        return False
    del node[parts[-1]]
    _save(path, data)
    return True


def install_user_config(path: Path) -> bool:
    """Create the user config at installation, with the keys tied to Q3TUI at their defaults. An existing file
    is never touched. True when it was created."""
    if path.exists():
        return False
    defaults = Config()
    lines = ["# Q3TUI user config: yours, on this machine. A project's .q3tui/config.yaml overrides it,",
             "# and --config key=value overrides both for one session.", ""]
    sections: dict[str, list[str]] = {}
    for dotted in INSTALLED_KEYS:
        section, key = dotted.split(".", 1)
        sections.setdefault(section, []).append(f"  {key}: {getattr(getattr(defaults, section), key)}")
    for section, keys in sections.items():
        lines += [f"{section}:", *keys, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return True
