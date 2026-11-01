"""The config's layers, how they merge, and how they are checked (spec/config.md).

From lowest to highest: default (the schema), user (`$Q3TUI_HOME/config.yaml`), project
(`<project>/.q3tui/config.yaml`), session (`--config key=value` and the title bar's menus, in memory).
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from q3tui.config.schema import Config

LAYERS = ("default", "user", "project", "session")
FILE_LAYERS = ("user", "project")


class ConfigError(Exception):
    """A config that cannot be used: Q3TUI stops before the TUI appears."""

    def __init__(self, message: str, file: Path | str | None = None, line: int | None = None):
        where = f"{file}:{line}: " if file and line else (f"{file}: " if file else "")
        super().__init__(where + message)
        self.file, self.line, self.reason = file, line, message


@dataclass
class ConfigWarning:
    key: str
    message: str
    file: Path | str | None = None
    line: int | None = None

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}: " if self.file and self.line else (f"{self.file}: " if self.file else "")
        return f"{where}{self.key}: {self.message}"


@dataclass
class Layer:
    name: str
    file: Path | None = None
    data: dict = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)  # dotted key -> line in the file


# -- reading ----------------------------------------------------------------------------------


def _read_file(path: Path, name: str) -> Layer:
    """A YAML file as a layer, with the line of every key; a file that is not YAML is a ConfigError."""
    layer = Layer(name, path)
    if not path.is_file():
        return layer
    text = path.read_text()
    try:
        from ruamel.yaml import YAML

        data = YAML(typ="rt").load(text)
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        raise ConfigError(f"not valid YAML ({getattr(exc, 'problem', None) or exc})", path,
                          mark.line + 1 if mark else None) from exc
    if data is None:
        return layer
    if not isinstance(data, dict):
        raise ConfigError("the top level must be a mapping", path, 1)
    lines: dict[str, int] = {}

    def walk(node, prefix: str) -> None:
        lc = getattr(node, "lc", None)
        for key in node:
            dotted = f"{prefix}{key}"
            if lc is not None:
                try:
                    lines[dotted] = lc.key(key)[0] + 1
                except (KeyError, TypeError):
                    pass
            if isinstance(node[key], dict):
                walk(node[key], dotted + ".")

    walk(data, "")
    layer.data = _plain(data)
    layer.lines = lines
    return layer


def _plain(node):
    if isinstance(node, dict):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    if hasattr(node, "__float__") and not isinstance(node, (bool, int, float)):
        return float(node)
    if isinstance(node, str):
        return str(node)
    return node


def parse_session_options(options: list[str]) -> dict:
    """`--config key=value` options as a nested dict; the value is read as YAML."""
    out: dict = {}
    for opt in options:
        key, sep, raw = opt.partition("=")
        if not sep or not key.strip():
            raise ConfigError(f"--config needs key=value, got `{opt}`")
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ConfigError(f"--config {key}: the value is not YAML ({exc})") from exc
        _set(out, key.strip(), value)
    return out


def _set(data: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    node = data
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = {}
        node = node[p]
    node[parts[-1]] = value


def _get(data: dict, dotted: str, default=None):
    node: Any = data
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return default
        node = node[p]
    return node


def _has(data: dict, dotted: str) -> bool:
    sentinel = object()
    return _get(data, dotted, sentinel) is not sentinel


# -- merging ----------------------------------------------------------------------------------


def merge(low: dict, high: dict) -> dict:
    """Maps merge key by key; a number, string, bool or list replaces; `null` removes the key."""
    out = copy.deepcopy(low)
    for key, value in high.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        elif isinstance(value, dict):
            out[key] = merge({}, value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# -- unknown keys -----------------------------------------------------------------------------


def _model_of(annotation):
    """The pydantic model a field holds directly, or the model of the values of a dict field."""
    import typing

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    if origin is dict and len(args) == 2:
        inner = args[1]
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return inner, True
        return None, True
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
        for a in args:
            model, is_map = _model_of(a)
            if model is not None:
                return model, is_map
    return None, False


def strip_unknown(data: dict, model: type[BaseModel] = Config, prefix: str = "") -> tuple[dict, list[tuple[str, str]]]:
    """`data` without the keys `model` does not know, and those keys with a hint of the closest known one."""
    out: dict = {}
    unknown: list[tuple[str, str]] = []
    fields = model.model_fields
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if key not in fields:
            close = difflib.get_close_matches(key, list(fields), n=1)
            unknown.append((dotted, f"did you mean `{close[0]}`?" if close else "not a key of this section"))
            continue
        sub, is_map = _model_of(fields[key].annotation)
        if sub is not None and isinstance(value, dict):
            if is_map:
                kept = {}
                for name, entry in value.items():
                    if isinstance(entry, dict):
                        kept[name], more = strip_unknown(entry, sub, f"{dotted}.{name}.")
                        unknown += more
                    else:
                        kept[name] = entry
                out[key] = kept
            else:
                out[key], more = strip_unknown(value, sub, dotted + ".")
                unknown += more
        else:
            out[key] = value
    return out, unknown


def _empty_values(layer: Layer) -> list[ConfigWarning]:
    """`key:` with nothing after it is `null`, which removes the key: often a slip, so it is said."""
    out = []
    if layer.file is None or not layer.file.is_file():
        return out
    text = layer.file.read_text().splitlines()

    def walk(node, prefix):
        for key, value in node.items():
            dotted = f"{prefix}{key}"
            if value is None:
                line = layer.lines.get(dotted)
                src = text[line - 1] if line and line <= len(text) else ""
                after = src.split(":", 1)[1].split("#", 1)[0].strip() if ":" in src else "x"
                if not after:
                    out.append(ConfigWarning(dotted, "an empty value is null: it removes the key", layer.file, line))
            elif isinstance(value, dict):
                walk(value, dotted + ".")

    walk(layer.data, "")
    return out


# -- the layers -------------------------------------------------------------------------------


class ConfigLayers:
    """The four layers, merged into one `Config`."""

    def __init__(self, user_file: Path | None, project_file: Path | None, session: dict | None = None):
        self.user_file, self.project_file = user_file, project_file
        self.session: dict = session or {}
        self.warnings: list[ConfigWarning] = []
        self.layers: dict[str, Layer] = {}
        self.config: Config = Config()
        self.reload()

    def reload(self) -> Config:
        layers = {
            "default": Layer("default", None, Config().model_dump(mode="json")),
            "user": _read_file(self.user_file, "user") if self.user_file else Layer("user"),
            "project": _read_file(self.project_file, "project") if self.project_file else Layer("project"),
            "session": Layer("session", None, copy.deepcopy(self.session)),
        }
        warnings: list[ConfigWarning] = []
        for name in ("user", "project", "session"):
            layer = layers[name]
            warnings += _empty_values(layer)
            layer.data, unknown = strip_unknown(layer.data)
            for dotted, hint in unknown:
                warnings.append(ConfigWarning(dotted, f"unknown key, ignored ({hint})", layer.file or "--config",
                                              layer.lines.get(dotted)))
        merged: dict = {}
        for name in LAYERS:
            merged = merge(merged, layers[name].data)
        try:
            config = Config.model_validate(merged)
        except ValidationError as exc:
            first = exc.errors()[0]
            dotted = ".".join(str(p) for p in first["loc"])
            name = self._layer_of(layers, dotted)
            layer = layers[name]
            raise ConfigError(f"{dotted}: {first['msg']}", layer.file or ("--config" if name == "session" else None),
                              layer.lines.get(dotted)) from exc
        self.layers, self.warnings, self.config = layers, warnings, config
        return config

    @staticmethod
    def _layer_of(layers: dict[str, Layer], dotted: str) -> str:
        """The highest layer that sets `dotted` (or a key above it)."""
        parts = dotted.split(".")
        for name in reversed(LAYERS):
            for i in range(len(parts), 0, -1):
                if _has(layers[name].data, ".".join(parts[:i])):
                    return name
        return "default"

    # -- reading values ---------------------------------------------------------------------

    def source(self, dotted: str) -> str:
        """The layer the value of `dotted` comes from: session, project, user or default."""
        for name in reversed(LAYERS):
            if _has(self.layers[name].data, dotted):
                return name
        return "default"

    def layer_value(self, layer: str, dotted: str, default=None):
        return _get(self.layers[layer].data, dotted, default)

    def gate_mode(self, step_id: str) -> str | None:
        """The gate the config sets for a step, or None (the flow files decide): the highest layer that sets
        `steps.<id>.gate` or `pipeline.gate_mode`; in one layer, the step's own key wins."""
        for name in ("session", "project", "user"):
            data = self.layers[name].data
            own = _get(data, f"steps.{step_id}.gate")
            if own is not None:
                return own
            flow_wide = _get(data, "pipeline.gate_mode")
            if flow_wide is not None:
                return flow_wide
        return None

    # -- the session layer ------------------------------------------------------------------

    def session_set(self, dotted: str, value) -> Config:
        """Set a value in the session layer (never written to a file)."""
        before = copy.deepcopy(self.session)
        _set(self.session, dotted, value)
        try:
            return self.reload()
        except ConfigError:
            self.session = before
            self.reload()
            raise

    def session_unset(self, dotted: str) -> Config:
        parts = dotted.split(".")
        node = self.session
        for p in parts[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
            if node is None:
                return self.config
        if isinstance(node, dict):
            node.pop(parts[-1], None)
        return self.reload()
