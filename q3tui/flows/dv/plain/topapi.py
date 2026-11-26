"""What tb_top offers a test case, by code: tb_top.sv without the bodies of its tasks, functions and always / initial blocks.

Every test-group writer and reviewer used to read the whole tb_top.sv (rv32iv: 1339 lines, 82k characters) and keep it in its context for
every later turn. The digest keeps what a test case needs: the comments, the parameters, macros, types, signals and monitor counters at
module scope, each task's / function's prototype with the comment above it, and the line numbers, so a stage reads a body
(`Read offset/limit`) only when it needs to know how a task works.
"""

from __future__ import annotations

import re

_SUB = re.compile(r"^\s*(?:(?:static|automatic|virtual|protected|local)\s+)*(task|function)\b")
_END_SUB = re.compile(r"^\s*(endtask|endfunction)\b")
_BLOCK = re.compile(r"^\s*(always(?:_ff|_comb|_latch)?|initial|final)\b")
_OPEN = re.compile(r"\b(begin|fork|case[xz]?|randcase)\b")
_RULE = re.compile(r"^\s*//\s*[-=*#~]{6,}\s*$")  # a comment that is only a separator line
_CLOSE = re.compile(r"\b(end|join(?:_any|_none)?|endcase)\b")


def _code(line: str) -> str:
    """The line without its comment and string literals (for counting begin / end)."""
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    return line.split("//", 1)[0]


def _depth(line: str) -> int:
    c = _code(line)
    return len(_OPEN.findall(c)) - len(_CLOSE.findall(c))


def digest(text: str) -> str:
    """tb_top.sv with the bodies left out; each kept line is prefixed with its line number."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    def keep(k: int) -> None:  # (alignment spaces dropped: a third of the characters of a column-aligned declaration block)
        out.append(f"{k + 1}: " + re.sub(r"(?<=\S) {2,}", " ", lines[k].strip()))

    while i < n:
        line = lines[i]
        if _SUB.match(line) and not re.search(r"\bextern\b", line):
            start = i
            keep(i)  # the prototype: up to the `;` that ends it
            while ";" not in _code(lines[i]) and i + 1 < n:
                i += 1
                keep(i)
            j = i + 1
            while j < n and not _END_SUB.match(lines[j]):
                j += 1
            if j > i + 1:
                out.append(f"  … body: lines {i + 2}–{j}")
            i = j + 1
            if start == i:  # (no end found)
                i += 1
            continue
        if _BLOCK.match(line):
            keep(i)
            d = _depth(line)
            j = i
            if d > 0:
                while d > 0 and j + 1 < n:
                    j += 1
                    d += _depth(lines[j])
            elif ";" not in _code(line):  # one statement over several lines (or `always @(...)` then `begin` on the next line)
                while j + 1 < n:
                    j += 1
                    d += _depth(lines[j])
                    if d <= 0 and ";" in _code(lines[j]):
                        break
            if j > i:
                out.append(f"  … body: lines {i + 2}–{j + 1}")
            i = j + 1
            continue
        if line.strip() and not _RULE.match(line):
            keep(i)
        i += 1
    return "\n".join(out)


def section(text: str, top_path: str) -> str:
    """The prompt section: the digest, and how to read a body."""
    return ("## tb_top: những gì TC dùng được (Q3TUI trích từ " + f"`{top_path}`" + ": tham số, macro, kiểu, tín hiệu, bộ đếm monitor, "
            "prototype của mọi task / function với comment của nó; bỏ thân hàm)\n"
            "Số đầu dòng là số dòng trong file. Cần biết một task làm gì chi tiết hơn comment: `Read` đúng đoạn đó "
            "(`offset` / `limit` theo \"body: lines a–b\"), không đọc cả file.\n```systemverilog\n" + digest(text) + "\n```")
