"""Log readers: a tool's log read into diagnostics (spec/tools.md "Log readers"). Addons add their own."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Diagnostic:
    severity: str  # error | warning
    message: str
    file: str | None = None
    line: int | None = None
    code: str = ""


Reader = Callable[[str], list[Diagnostic]]

_LOC = r"(?P<file>[^\s:]+\.\w+):(?P<line>\d+)(?::\d+)?"


def _sev(word: str) -> str:
    return "error" if word.lower() in ("error", "fatal", "fail", "failed") else "warning"


# -- Synopsys VCS -------------------------------------------------------------------------------------
# Error-[SE] Syntax error
#   Following verilog source has syntax error :
#   "rtl/foo.sv", 12: token is 'endmodule'
_VCS_HDR = re.compile(r"^(Error|Warning|Lint|Note)-\[([\w-]+)\]\s*(.*)$")
_VCS_LOC = re.compile(r'^\s*"?([^",\s]+\.\w+)"?,\s*(\d+)')
_VCS_WRAPPED_LOC = re.compile(r'"([^"\s]+\.\w+)",\s*(\d+)')
_UVM_ERR = re.compile(r"^(UVM_ERROR|UVM_FATAL)\s+(\S+)\((\d+)\)\s*@\s*[^:]*:\s*(.*)$")
_SV_ERR = re.compile(r'^(Error|Fatal):\s*"?([^",\s]+)"?,\s*(\d+)[:,]?\s*(.*)$')
_VCS_SEV = {"Error": "error", "Warning": "warning", "Lint": "warning"}


def read_vcs(text: str) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _VCS_HDR.match(line)
        if m:
            kind, code, title = m.groups()
            if kind not in _VCS_SEV:
                continue
            file, lineno, detail = None, None, []
            for follow in lines[i + 1:i + 8]:
                if not follow.strip() or _VCS_HDR.match(follow):
                    break
                loc = _VCS_LOC.match(follow)
                if loc and file is None:
                    file, lineno = loc.group(1), int(loc.group(2))
                detail.append(follow.strip())
            if file is None and detail:  # a long path wraps: `"/very/long/path.sv", ⏎ 407: token is …`
                wrapped = _VCS_WRAPPED_LOC.search(" ".join(detail))
                if wrapped:
                    file, lineno = wrapped.group(1), int(wrapped.group(2))
            message = title + (" — " + " ".join(detail) if detail else "")
            out.append(Diagnostic(_VCS_SEV[kind], message[:500], file, lineno, code))
            continue
        m = _UVM_ERR.match(line)
        if m:
            out.append(Diagnostic("error", m.group(4)[:500], m.group(2), int(m.group(3)), m.group(1)))
            continue
        m = _SV_ERR.match(line)
        if m:
            out.append(Diagnostic("error", m.group(4)[:500], m.group(2), int(m.group(3)), "RUNTIME"))
    return out


# -- Design Compiler ----------------------------------------------------------------------------------
_DC = re.compile(rf"^(?P<sev>Error|Warning):\s*(?:{_LOC}:\s*)?(?P<msg>.*?)(?:\s*\((?P<code>[A-Z]{{2,6}}-\d+)\))?\.?\s*$")


def read_dc(text: str) -> list[Diagnostic]:
    """`Error: file:line: message (VER-294).`, `Warning: … (OPT-1006)`."""
    out = []
    for line in text.splitlines():
        m = _DC.match(line)
        if m:
            out.append(Diagnostic(_sev(m["sev"]), m["msg"][:500], m["file"], int(m["line"]) if m["line"] else None,
                                  m["code"] or m["sev"].upper()))
    return out


# -- Verilator ----------------------------------------------------------------------------------------
_VERILATOR = re.compile(rf"^%(?P<sev>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?:\s*(?:{_LOC}:\s*)?(?P<msg>.*)$")
_VERILATOR_SUMMARY = re.compile(r"^%Error: Exiting due to \d+ (?:warning|error)\(s\)")


def read_verilator(text: str) -> list[Diagnostic]:
    out = []
    for line in text.splitlines():
        m = _VERILATOR.match(line)
        if m and not _VERILATOR_SUMMARY.match(line):  # the count of the findings above is not a finding
            out.append(Diagnostic(_sev(m["sev"]), m["msg"][:500], m["file"], int(m["line"]) if m["line"] else None,
                                  m["code"] or m["sev"].upper()))
    return out


# -- Icarus Verilog -----------------------------------------------------------------------------------
_IVERILOG = re.compile(rf"^{_LOC}:\s*(?P<sev>error|warning|sorry):\s*(?P<msg>.*)$")


def read_iverilog(text: str) -> list[Diagnostic]:
    out = []
    for line in text.splitlines():
        m = _IVERILOG.match(line)
        if m:  # ("sorry: … not currently supported" is a note: Icarus goes on and counts its real errors apart)
            out.append(Diagnostic(_sev(m["sev"]), m["msg"][:500], m["file"], int(m["line"]), m["sev"].upper()))
            continue
        if line.startswith(("ERROR:", "FATAL:")) or ("$fatal" in line.lower() and "called" in line.lower()):
            out.append(Diagnostic("error", line[:500], code="RUNTIME"))
    return out


# -- Yosys --------------------------------------------------------------------------------------------
_YOSYS = re.compile(r"^(?P<sev>ERROR|Warning|WARNING):\s*(?P<msg>.*)$")


def read_yosys(text: str) -> list[Diagnostic]:
    out = []
    for line in text.splitlines():
        m = _YOSYS.match(line)
        if m:
            out.append(Diagnostic(_sev(m["sev"]), m["msg"][:500], code=m["sev"].upper()))
    return out


# -- Vivado -------------------------------------------------------------------------------------------
_VIVADO = re.compile(r"^(?P<sev>ERROR|CRITICAL WARNING|WARNING):\s*\[(?P<code>[\w -]+)\]\s*(?P<msg>.*)$")


def read_vivado(text: str) -> list[Diagnostic]:
    """`ERROR: [Synth 8-439] …`, `CRITICAL WARNING: [Constraints 18-4427] …`, `WARNING: [Synth 8-3331] …`."""
    out = []
    for line in text.splitlines():
        m = _VIVADO.match(line)
        if m:
            out.append(Diagnostic("error" if m["sev"] == "ERROR" else "warning", m["msg"][:500],
                                  code=m["sev"] if m["sev"] == "CRITICAL WARNING" else m["code"]))
    return out


# -- Verible ------------------------------------------------------------------------------------------
_VERIBLE = re.compile(r"^(?:\S+\.\w+:\s+)?(?P<file>[^\s:]+\.\w+):(?P<line>\d+):(?P<col>\d+)(?:-\d+)?:\s*(?P<msg>.*?)\s*$")
_VERIBLE_TOOL = re.compile(r"^(?:ERROR:|[EF]\d{4}\s+\S+\s+\d+\s+\S+\]\s)\s*(?P<msg>.*)$")
_VERIBLE_RULE = re.compile(r"\s*\[(?P<rule>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)\]\s*$")


def read_verible(text: str) -> list[Diagnostic]:
    """`file:line:col: message [Style: section] [rule-name]`: a finding with a rule is a warning; a syntax error is an
    error; a refusal of the tool itself (`ERROR: Illegal value …`) is an error with no file."""
    out = []
    for line in text.splitlines():
        t = _VERIBLE_TOOL.match(line)
        if t:
            out.append(Diagnostic("error", t["msg"][:500], code="TOOL"))
            continue
        m = _VERIBLE.match(line)
        if not m:
            continue
        msg = m["msg"]
        rule = _VERIBLE_RULE.search(msg)
        if rule:
            text_ = re.sub(r"\s*\[Style:[^\]]*\]", "", _VERIBLE_RULE.sub("", msg))
            out.append(Diagnostic("warning", text_[:500], m["file"], int(m["line"]), rule["rule"]))
        elif "syntax error" in msg.lower() or msg.lower().startswith(("error", "lex")):
            out.append(Diagnostic("error", msg[:500], m["file"], int(m["line"]), "SYNTAX"))
    return out


# -- generic ------------------------------------------------------------------------------------------
GENERIC = {"error": [r"\berror\b", r"\bfatal\b"], "warning": [r"\bwarning\b"]}


def read_generic(text: str, patterns: dict | None = None) -> list[Diagnostic]:
    """A line with `error` or `fatal` is an error, one with `warning` a warning, whatever their case; the patterns
    given for a severity replace its default ones."""
    given = patterns or {}
    compiled = {sev: [re.compile(p) for p in given[sev]] if sev in given else [re.compile(p, re.IGNORECASE) for p in ps]
                for sev, ps in GENERIC.items()}
    out = []
    for line in text.splitlines():
        for sev in ("error", "warning"):
            if any(p.search(line) for p in compiled.get(sev, [])):
                out.append(Diagnostic(sev, line.strip()[:500], code=sev.upper()))
                break
    return out


BUILT_IN: dict[str, Reader] = {"vcs": read_vcs, "dc": read_dc, "verilator": read_verilator, "iverilog": read_iverilog,
                               "yosys": read_yosys, "vivado": read_vivado, "verible": read_verible,
                               "generic": read_generic}


def read_log(parse: str | dict, text: str, extra: dict[str, Reader] | None = None) -> list[Diagnostic]:
    """Read a log with the role's `parse`: a reader's name (built in, or registered by an addon) or patterns."""
    if isinstance(parse, dict):
        return read_generic(text, parse)
    reader = (extra or {}).get(parse) or BUILT_IN.get(parse or "generic")
    if reader is None:
        known = ", ".join([*BUILT_IN, *(extra or {})])
        raise ValueError(f"unknown log reader `{parse}` (known: {known}, or {{error: [...], warning: [...]}})")
    return reader(text)
