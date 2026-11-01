"""The pass checks of a step (spec/flow.md "`pass`"), run by the engine whatever the step's code does."""

from __future__ import annotations

import ast
import operator
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from q3tui.engine.artifacts import Artifacts, json_path, read_json
from q3tui.flowdef.model import Instance

OPS = {"==": operator.eq, "!=": operator.ne, ">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt}


@dataclass
class CheckResult:
    check: str
    status: str  # pass | fail | na
    reason: str = ""
    on_fail: str = "fail"


class CheckError(Exception):
    pass


def _value(text: str, params: dict):
    if text in params:
        return params[text]
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    if text in ("true", "false"):
        return text == "true"
    return text.strip("'\"")


_AST_OPS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.GtE: operator.ge, ast.LtE: operator.le,
            ast.Gt: operator.gt, ast.Lt: operator.lt}


def expression(text: str, names: dict):
    """A small expression: names, numbers, strings, comparisons, `and`, `or`, `not`, parentheses."""
    text = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", text))

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BoolOp):
            values = [ev(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, right in zip(node.ops, node.comparators, strict=True):
                r = ev(right)
                if type(op) not in _AST_OPS:
                    raise CheckError(f"operator not allowed in `{text}`")
                if not _AST_OPS[type(op)](left, r):
                    return False
                left = r
            return True
        if isinstance(node, ast.Name):
            if node.id in ("True", "False"):
                return node.id == "True"
            if node.id not in names:
                raise CheckError(f"`{node.id}` is unknown in `{text}` (known: {', '.join(sorted(names))})")
            return names[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        raise CheckError(f"cannot read `{text}`")

    try:
        return ev(ast.parse(text, mode="eval"))
    except SyntaxError as exc:
        raise CheckError(f"cannot read `{text}`") from exc


class Checker:
    def __init__(self, inst: Instance, artifacts: Artifacts, root: Path, *, tools: dict[str, dict],
                 code_check: Callable[[str], bool | str] | None = None,
                 allow_run: Callable[[str], bool] | None = None):
        self.inst, self.artifacts, self.root = inst, artifacts, root
        self.tools, self.code_check, self.allow_run = tools, code_check, allow_run

    def run_all(self) -> list[CheckResult]:
        out = []
        for c in self.inst.passes:
            try:
                status, reason = self.one(c["check"])
            except CheckError as exc:
                status, reason = "fail", str(exc)
            except Exception as exc:  # noqa: BLE001 -- a check that cannot be evaluated does not hold
                status, reason = "fail", f"{type(exc).__name__}: {exc}"
            out.append(CheckResult(c["check"], status, reason, c.get("on_fail", "fail")))
        return out

    def one(self, check: str) -> tuple[str, str]:
        kind, _, rest = check.strip().partition(" ")
        rest = rest.strip()
        params = self.inst.params
        if kind == "exists":
            return ("pass", "") if self.artifacts.exists(rest, self.inst) else ("fail", f"`{rest}` is not on disk")
        if kind == "contains":
            art, _, regex = rest.partition(" ")
            pat = re.compile(regex.strip())
            for f in self.artifacts.files(art, self.inst):
                if pat.search(f.read_text(errors="replace")):
                    return "pass", ""
            return "fail", f"no file of `{art}` matches `{regex.strip()}`"
        if kind == "json":
            m = re.fullmatch(r"(\S+)\s+(\$\S*)\s+(length\s+)?(==|!=|>=|<=|>|<)\s+(.+)", rest)
            if not m:
                raise CheckError(f"cannot read the check `{check}`")
            art, path, length, op, want = m.groups()
            values = json_path(read_json(self.artifacts.files(art, self.inst)), path)
            if not values:
                return "fail", f"`{path}` is not in `{art}`"
            value = values[0] if len(values) == 1 else values
            if length:
                value = len(value) if isinstance(value, (list, dict, str)) else 0
            target = _value(want.strip(), params)
            ok = OPS[op](value, target)
            return ("pass", "") if ok else ("fail", f"`{art}` {path}{' length' if length else ''} is {value!r}")
        if kind == "tool":
            role, _, expr = rest.partition(" ")
            tool_decl = next((t for t in self.inst.tools if t["role"] == role), None)
            result = self.tools.get(role)
            if result is None or result.get("na"):
                if tool_decl is not None and not tool_decl["required"]:
                    return "na", f"the tool `{role}` is not available"
                return "fail", f"the tool `{role}` did not run"
            names = {**params, **{k: result.get(k) for k in ("ok", "errors", "warnings", "returncode", "timed_out")}}
            return ("pass", "") if expression(expr, names) else ("fail", f"`{expr}` does not hold")
        if kind == "code":
            if self.code_check is None:
                raise CheckError(f"`code {rest}`: the step has no step.py")
            res = self.code_check(rest)
            if res is True:
                return "pass", ""
            return "fail", res if isinstance(res, str) else f"check_{rest} says no"
        if kind == "run":
            if self.allow_run is not None and not self.allow_run(rest):
                return "fail", f"the command `{rest}` of the project is not allowed yet"
            proc = subprocess.run(["bash", "-c", rest], cwd=self.root, capture_output=True, text=True, check=False)
            return ("pass", "") if proc.returncode == 0 else ("fail", f"`{rest}` exited with {proc.returncode}")
        raise CheckError(f"unknown check `{kind}`")
