"""File tools for the Codex backend, served by Q3TUI (`mcp__q3tui__read_file` …).

Claude confines `Read/Grep/Glob/Edit/Write` with a PreToolUse hook. Codex's own shell and file tools cannot be confined to
a stage's folders (a shell command reads anything), so the backend turns that shell off and offers these tools instead; each
call goes through the same rules (`runtime.guard_reason`): the stage's folders, `deny_dirs`, `write_dirs` / `write_files`,
the role's task tools, its NOTES.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from q3tui.llm import runtime
from q3tui.llm.runtime import Stage
from q3tui.llm.tooldef import LlmTool, tool

# Claude's built-in tool name → the tool that replaces it, and the name the guard knows it by
FILE_TOOL_NAMES = {"Read": "read_file", "Grep": "grep", "Glob": "glob", "Write": "write_file", "Edit": "edit_file"}
GUARD_NAME = {"read_file": "Read", "grep": "Grep", "glob": "Glob", "write_file": "Write", "edit_file": "Edit"}
GREP_LIMIT = 200
READ_LIMIT = 2000  # lines


def _text(s: str, error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if error:
        out["is_error"] = True
    return out


def _resolve(stage: Stage, raw: str) -> Path:
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else stage.cwd / p).resolve()


def _denied(stage: Stage, name: str, args: dict[str, Any]) -> str | None:
    return runtime.guard_reason(stage, GUARD_NAME[name], args)


def file_tools(stage: Stage) -> list[LlmTool]:
    """The tools for the built-in file tools the stage was given (`Stage.builtin_tools`)."""
    want = {FILE_TOOL_NAMES[t] for t in stage.builtin_tools if t in FILE_TOOL_NAMES}
    tools: list[LlmTool] = []

    @tool("read_file", "Read a text file (like Read): `file_path`, optional `offset` (first line, 1-based) and `limit` (lines).",
          {"type": "object", "properties": {"file_path": {"type": "string"}, "offset": {"type": "integer"},
                                            "limit": {"type": "integer"}}, "required": ["file_path"]})
    async def read_file(args: dict) -> dict:
        reason = _denied(stage, "read_file", {"file_path": args.get("file_path", "")})
        if reason:
            return _text(reason, True)
        path = _resolve(stage, args["file_path"])
        if not path.is_file():
            return _text(f"{args['file_path']}: no such file", True)
        lines = path.read_text(errors="replace").splitlines()
        start = max(1, int(args.get("offset") or 1))
        end = start - 1 + int(args.get("limit") or READ_LIMIT)
        body = "\n".join(f"{n}\t{line}" for n, line in enumerate(lines[start - 1:end], start))
        more = f"\n… ({len(lines) - end} more lines; pass offset={end + 1})" if len(lines) > end else ""
        return _text(body + more if lines else "(empty file)")

    @tool("grep", "Search file contents with a regular expression (like Grep): `pattern`, optional `path` (a file or a folder "
                  "this task may read), `glob` (file name filter, e.g. *.sv), `ignore_case`.",
          {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"},
                                            "glob": {"type": "string"}, "ignore_case": {"type": "boolean"}}, "required": ["pattern"]})
    async def grep(args: dict) -> dict:
        reason = _denied(stage, "grep", {"path": args.get("path") or ""} if args.get("path") else {})
        if reason:
            return _text(reason, True)
        try:
            rx = re.compile(args["pattern"], re.I if args.get("ignore_case") else 0)
        except re.error as exc:
            return _text(f"bad pattern: {exc}", True)
        root = _resolve(stage, args.get("path") or ".")
        denied = [d.resolve() for d in stage.deny_dirs]
        files = [root] if root.is_file() else sorted(p for p in root.rglob(args.get("glob") or "*") if p.is_file())
        hits: list[str] = []
        for p in files:
            rel = p.relative_to(stage.cwd) if p.is_relative_to(stage.cwd) else p
            if runtime._within(p.resolve(), denied) or "__pycache__" in p.parts \
                    or any(part.startswith(".") for part in (p.relative_to(root).parts if root.is_dir() else ())):
                continue
            try:
                for n, line in enumerate(p.read_text().splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{rel}:{n}:{line.strip()[:300]}")
                        if len(hits) >= GREP_LIMIT:
                            return _text("\n".join(hits) + f"\n… (first {GREP_LIMIT} matches; narrow the search)")
            except (UnicodeDecodeError, OSError):
                continue
        return _text("\n".join(hits) or "No matches found")

    @tool("glob", "Find files by glob pattern (e.g. \"**/*.md\"), optionally under a directory (`path`). Lists only files this "
                  "task may use.", {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                                    "required": ["pattern"]})
    async def glob(args: dict) -> dict:
        return _text(runtime.safe_glob(stage, args.get("pattern") or "*", args.get("path") or None))

    @tool("write_file", "Write a file (like Write): `file_path`, `content` (the whole file; folders are created).",
          {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
           "required": ["file_path", "content"]})
    async def write_file(args: dict) -> dict:
        reason = _denied(stage, "write_file", {"file_path": args.get("file_path", "")})
        if reason:
            return _text(reason, True)
        path = _resolve(stage, args["file_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"])
        return _text(f"wrote {args['file_path']} ({len(args['content'])} characters)")

    @tool("edit_file", "Replace text in a file (like Edit): `file_path`, `old_string` (must be unique unless `replace_all`), "
                       "`new_string`.",
          {"type": "object", "properties": {"file_path": {"type": "string"}, "old_string": {"type": "string"},
                                            "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
           "required": ["file_path", "old_string", "new_string"]})
    async def edit_file(args: dict) -> dict:
        reason = _denied(stage, "edit_file", {"file_path": args.get("file_path", "")})
        if reason:
            return _text(reason, True)
        path = _resolve(stage, args["file_path"])
        if not path.is_file():
            return _text(f"{args['file_path']}: no such file", True)
        text, old = path.read_text(), args["old_string"]
        count = text.count(old)
        if not old or count == 0:
            return _text("old_string was not found in the file", True)
        if count > 1 and not args.get("replace_all"):
            return _text(f"old_string occurs {count} times: add context to make it unique, or pass replace_all", True)
        path.write_text(text.replace(old, args["new_string"]) if args.get("replace_all") else text.replace(old, args["new_string"], 1))
        return _text(f"edited {args['file_path']}")

    for t in (read_file, grep, glob, write_file, edit_file):
        if t.name in want:
            tools.append(t)
    return tools


def usage_note(stage: Stage) -> str:
    """Tells the model which tool does what Claude's names mean (the prompts are written with Claude's names)."""
    names = [f"{c} → mcp__{runtime.Q3TUI_MCP}__{FILE_TOOL_NAMES[c]}" for c in stage.builtin_tools if c in FILE_TOOL_NAMES]
    note = ("\n\nFile access: you have no shell and no patch tool; every file is read and written with the Q3TUI tools. "
            "Where the instructions name a tool, use its replacement: " + ", ".join(names) + "." if names else
            "\n\nYou have no file tools in this task; answer from the prompt and the Q3TUI tools.")
    return note + " `StructuredOutput` / `submit` mean: give the result as the instructions say."
