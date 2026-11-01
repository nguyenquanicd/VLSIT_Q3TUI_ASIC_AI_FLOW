"""The text of a flow file: its front matter, its sections, placeholders, conditions (spec/flow.md)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
MARK = re.compile(r"<!--\s*(/?)\s*([^>]*?)\s*-->")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
SYSTEM_PROMPT = "SYSTEM PROMPT"


class FlowFileError(Exception):
    def __init__(self, file: Path | str, message: str):
        super().__init__(f"{file}: {message}")
        self.file, self.reason = file, message


def split(path: Path) -> tuple[dict, str]:
    """The front matter (a mapping) and the body of a FLOW.md / STAGE.md / STEP.md / SKILL.md."""
    text = path.read_text()
    m = FRONT.match(text)
    if not m:
        raise FlowFileError(path, "no front matter (a YAML block between two `---` lines at the top)")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise FlowFileError(path, f"the front matter is not YAML ({exc})") from exc
    if not isinstance(meta, dict):
        raise FlowFileError(path, "the front matter is not a mapping")
    return meta, m.group(2)


def sections(body: str, names: set[str]) -> tuple[dict[str, str], list[str]]:
    """The sections of `names` in a body (`<!-- name -->` … `<!-- /name -->`); every other HTML comment is
    plain text. Returns the sections and the problems found."""
    out: dict[str, str] = {}
    problems: list[str] = []
    open_name: str | None = None
    start = 0
    for m in MARK.finditer(body):
        closing, name = m.group(1) == "/", m.group(2)
        if name not in names:
            continue
        if not closing:
            if open_name is not None:
                problems.append(f"section `{open_name}` is not closed before `{name}`")
            open_name, start = name, m.end()
        elif name != open_name:
            problems.append(f"`<!-- /{name} -->` closes a section that is not open")
        else:
            if name in out:
                problems.append(f"section `{name}` appears twice")
            out[name] = body[start:m.start()].strip("\n")
            open_name = None
    if open_name is not None:
        problems.append(f"section `{open_name}` is not closed")
    return out, problems


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text)


def fill(text: str, values: dict, *, where: str = "") -> str:
    """Replace `{{name}}`; a placeholder with no value is an error that names it. A single `{…}` is plain text."""

    def one(m: re.Match) -> str:
        name = m.group(1)
        if name not in values or values[name] is None:
            raise KeyError(f"{where + ': ' if where else ''}placeholder `{{{{{name}}}}}` has no value")
        return str(values[name])

    return PLACEHOLDER.sub(one, text)


# -- conditions ---------------------------------------------------------------------------------

_TOKEN = re.compile(r"\s*(\(|\)|\[|\]|,|==|!=|'[^']*'|\"[^\"]*\"|[A-Za-z_][A-Za-z0-9_.\-]*|-?\d+(?:\.\d+)?)")


class ConditionError(ValueError):
    pass


def _tokens(text: str) -> list[str]:
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ConditionError(f"cannot read `{text[pos:]}` in `{text}`")
        out.append(m.group(1))
        pos = m.end()
    return out


def _literal(tok: str):
    if tok[0] in "'\"":
        return tok[1:-1]
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    if re.fullmatch(r"-?\d+\.\d+", tok):
        return float(tok)
    if tok in ("true", "false"):
        return tok == "true"
    if tok == "null":
        return None
    return tok


def check_condition(cond, params: set[str]) -> list[str]:
    """Problems of a condition: it must parse, and use only the given params."""
    if isinstance(cond, bool):
        return []
    try:
        _Parser(_tokens(str(cond)), None, params).parse()
    except ConditionError as exc:
        return [str(exc)]
    return []


def evaluate(cond, params: dict) -> bool:
    """`when` and `required` conditions, on params only: `==`, `!=`, `in [a, b]`, `and`, `or`, `not`, parentheses;
    a param alone means "set and not false"."""
    if isinstance(cond, bool):
        return cond
    if cond is None:
        return True
    return bool(_Parser(_tokens(str(cond)), params, set(params)).parse())


class _Parser:
    def __init__(self, tokens: list[str], values: dict | None, names: set[str]):
        self.t, self.i, self.values, self.names = tokens, 0, values, names

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, expected: str | None = None):
        tok = self.peek()
        if tok is None or (expected is not None and tok != expected):
            raise ConditionError(f"expected `{expected or 'more'}` in `{' '.join(self.t)}`")
        self.i += 1
        return tok

    def parse(self):
        value = self.or_()
        if self.peek() is not None:
            raise ConditionError(f"unexpected `{self.peek()}` in `{' '.join(self.t)}`")
        return value

    def or_(self):
        value = self.and_()
        while self.peek() == "or":
            self.take()
            right = self.and_()
            value = value or right
        return value

    def and_(self):
        value = self.not_()
        while self.peek() == "and":
            self.take()
            right = self.not_()
            value = value and right
        return value

    def not_(self):
        if self.peek() == "not":
            self.take()
            return not self.not_()
        return self.atom()

    def param(self, name: str):
        if name not in self.names:
            raise ConditionError(f"`{name}` is not a param")
        return None if self.values is None else self.values.get(name)

    def atom(self):
        tok = self.take()
        if tok == "(":
            value = self.or_()
            self.take(")")
            return value
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok) or tok in ("and", "or", "not", "in"):
            raise ConditionError(f"expected a param, got `{tok}`")
        left = self.param(tok)
        op = self.peek()
        if op in ("==", "!="):
            self.take()
            right = _literal(self.take())
            return (left == right) if op == "==" else (left != right)
        if op == "in":
            self.take()
            self.take("[")
            items = [_literal(self.take())]
            while self.peek() == ",":
                self.take()
                items.append(_literal(self.take()))
            self.take("]")
            return left in items
        return left not in (None, False, "", [], {})
