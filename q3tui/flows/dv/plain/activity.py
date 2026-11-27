"""Check activity of the plain testbench (the reference flow's `property_activity`, for `TC_CHECK`s): which checks of a test case ran, how often.

`gen.COMMON` makes every `TC_CHECK` count itself under `<file>:<line>` and `TC_REPORT` print `TC_CHECKS <tc> n=<k>` and one `TC_HIT <tc> <file>:<line> <n>`
per check that ran. A check that is not in the hits was never evaluated (a branch or loop the stimulus never reached): it checked nothing, like an
assertion whose antecedent never fired (vacuous). Code maps the hits to the test case file's checks and to the planned failure modes (the `// FM<k>:`
tag above a check), so the report can say which failure mode was never checked although the test passed."""

from __future__ import annotations

import re
from pathlib import Path

CHECKS = re.compile(r"^TC_CHECKS\s+(\S+)\s+n=(\d+)", re.M)
HIT = re.compile(r"^TC_HIT\s+(\S+)\s+(\S+):(\d+)\s+(\d+)", re.M)
SEED = re.compile(r"^TC_SEED\s+(\S+)\s+(-?\d+)", re.M)
CASES = re.compile(r"^TC_CASES\s+(\S+)\s+run=(\d+)\s+failed=(\d+)", re.M)
CASE_FAIL = re.compile(r"^TC_CASE_FAIL\s+(\S+)\s+(\S+)", re.M)
_CHECK = re.compile(r"`TC_CHECK\b")
_FM = re.compile(r"//\s*FM(\d+)\b")


def checks_in(text: str) -> list[int]:
    """The line numbers (1-based) of the `TC_CHECK`s of a file (commented-out ones left out)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("//", 1)[0]
        if _CHECK.search(code):
            out.append(n)
    return out


def fm_checks(text: str) -> dict[int, int]:
    """FM number -> the line of the check it tags (the first `TC_CHECK` at or after the tag)."""
    lines = text.splitlines()
    checks = checks_in(text)
    out: dict[int, int] = {}
    for n, line in enumerate(lines, 1):
        m = _FM.search(line)
        if m:
            nxt = next((c for c in checks if c >= n), None)
            if nxt is not None:
                out.setdefault(int(m.group(1)), nxt)
    return out


def parse(text: str, tc_id: str, tc_file: Path | None, failure_modes: list[str] | None = None) -> dict | None:
    """The activity of one test case from its log. None: the log has no `TC_CHECKS` line for it (a testbench built before the counters, or a run that
    never reached its report). `unreached`: the checks of its own file that never ran; `fm_unchecked`: the planned failure modes whose check never ran."""
    m = next((m for m in CHECKS.finditer(text) if m.group(1) == tc_id), None)
    if m is None:
        return None
    hits: dict[str, int] = {}
    for h in HIT.finditer(text):
        if h.group(1) == tc_id:
            key = f"{Path(h.group(2)).name}:{h.group(3)}"
            hits[key] = hits.get(key, 0) + int(h.group(4))
    seeds = [int(s.group(2)) for s in SEED.finditer(text) if s.group(1) == tc_id]
    out = {"checks_run": int(m.group(2)), "hits": hits, "seeds": seeds}
    cm = next((x for x in CASES.finditer(text) if x.group(1) == tc_id), None)
    if cm is not None:  # (a test with a case table / random cases: how many ran, which failed)
        out["cases"] = {"run": int(cm.group(2)), "failed": int(cm.group(3)),
                        "failed_ids": [x.group(2) for x in CASE_FAIL.finditer(text) if x.group(1) == tc_id]}
    if tc_file is not None and tc_file.is_file():
        src = tc_file.read_text(errors="replace")
        lines = checks_in(src)
        mine = {int(k.rsplit(":", 1)[1]): v for k, v in hits.items() if k.rsplit(":", 1)[0] == tc_file.name}

        def hit(line: int) -> int:
            # (a check written over several lines: the simulator may give any line of the call — the nearest hit at or after it, before the next check)
            nxt = next((c for c in lines if c > line), 10**9)
            return sum(v for ln, v in mine.items() if line <= ln < nxt)

        out["checks"] = len(lines)
        out["unreached"] = [ln for ln in lines if hit(ln) == 0]
        fms = fm_checks(src)
        out["fm_unchecked"] = [f"FM{k}" + (f" ({failure_modes[k - 1]})" if failure_modes and k <= len(failure_modes) else "")
                               for k, ln in sorted(fms.items()) if hit(ln) == 0]
    return out
