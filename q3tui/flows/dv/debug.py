"""Debug runs for the dv flow's simulation triage: run one failing test again with a waveform dump of the instances it names, and read the waveform.

The triage reads the spec, the testbench and the RTL; reading alone cannot always tell which side is wrong (rv32iv_sm: an illegal flag "correct on paper" never
reached the core, and the guessed module was handed a fix it could not find). With these tools it shows the fault on a run before it hands a fix over:

- `sim_probe(test, scopes, depth, until_ns)`: the tool role `wave` (config/tools.json; the Synopsys preset: VCS UCLI dumps a VPD, `vpd2vcd` makes the VCD) runs the
  test with the dump; the answer is the test's result lines and the dump's id (D1, D2, …) with its signals.
- `wave_list(dump, pattern)`, `wave_values(dump, signals, start_ns, end_ns)`, `wave_find(dump, signal, value, after_ns)`: read the VCD by code (`eda/vcd.py`).

Every dump made is recorded (`Probe.runs`): a verdict that hands a fix over cites one as its evidence (`cites`). The files are in build/sim/<tb>/debug/ (disposable)."""

from __future__ import annotations

import re
from pathlib import Path

ROLE = "wave"
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_RESULT = re.compile(r"\b(TC_RESULT|TC_DETAIL|UVM_(ERROR|FATAL)|Error-\[|Fatal|\$finish|SMOKE_RESULT)", re.I)


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def fill(template: str, variables: dict) -> str:
    """A role's script text with its placeholders filled; braces that are not a known placeholder (Tcl's) stay. A list becomes words."""
    def one(m: re.Match) -> str:
        v = variables.get(m.group(1))
        if v is None:
            return m.group(0)
        return " ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
    return re.sub(r"\{(\w+)\}", one, template)


class Probe:
    """The debug runs of one triage: `run` makes a dump, the readers answer from it."""

    def __init__(self, project, tools, work: Path, run_vars, tests: set[str] | None = None):
        self.project, self.tools, self.work = project, tools, work
        self.run_vars = run_vars  # test id → the variables of the `run` role for it ({tc}, {top}, {workdir}, …)
        self.tests = tests  # the tests that may be run (None: any)
        self.dir = work / "debug"
        self.runs: dict[str, dict] = {}  # D1 → {test, scopes, vcd, log, ok, signals}

    def run(self, test: str, scopes: list[str], depth: int = 1, until_ns: float | None = None) -> str:
        from q3tui.eda import vcd
        from q3tui.eda.tools import run_role

        test = test.strip()
        if self.tests is not None and test not in self.tests:
            return f"unknown test '{test}': one of {', '.join(sorted(self.tests))}"
        scopes = [s.strip() for s in scopes if s and s.strip()]
        if not scopes:
            return "give the instances to dump (scopes), e.g. tb_top.u_dut.u_core: hierarchical instance paths from the testbench top"
        role = self.tools.roles[ROLE]
        did = f"D{len(self.runs) + 1}"
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob(f"{did}.*"):
            old.unlink()
        files = {"script": self.dir / f"{did}.script", "dump": self.dir / f"{did}.dump", "vcd": self.dir / f"{did}.vcd"}
        variables = {**self.run_vars(test), **files, "scopes": scopes, "depth": max(0, int(depth)),
                     "until": f"{until_ns:g}ns" if until_ns else ""}
        if role.script:
            files["script"].write_text(fill(role.script, variables))
        try:
            res = run_role(self.tools, ROLE, self.work, variables, log_name=f"debug/{did}.log")
        except Exception as exc:  # noqa: BLE001 - a command that needs a placeholder this run has not, a tool that cannot start: said, not raised
            return f"{test}: the debug run could not start: {exc}"
        log = Path(res.log_path).read_text(errors="replace") if res.log_path and Path(res.log_path).is_file() else ""
        lines = [x for x in log.splitlines() if _RESULT.search(x)]
        result = "\n".join(lines[:30]) or "\n".join(log.splitlines()[-15:])
        errors = [f"{d.code} {d.message}".strip() for d in res.errors][:10]
        path = files["vcd"]
        h = vcd.header(path) if path.is_file() and path.stat().st_size else None
        if h is None or not h.vars:
            why = "; ".join(errors) or "no VCD was written"
            return (f"{test}: the debug run made no waveform ({why}). Check the instance paths (read the RTL for the instance names; from the testbench top, e.g. "
                    f"tb_top.u_dut.<instance>).\nLog (end):\n" + "\n".join(log.splitlines()[-20:]))
        self.runs[did] = {"test": test, "scopes": scopes, "vcd": str(path), "log": self.project.rel(Path(res.log_path)) if res.log_path else "", "signals": len(h.vars)}
        names = [v.name for v in h.vars]
        shown = names[:150]
        return (f"{did}: {test} ran with a dump of {', '.join(scopes)} (depth {depth}); {len(names)} signal(s), the run ends at {h.end_ns():g} ns."
                + (f"\nTool messages: {'; '.join(errors)}" if errors else "")
                + f"\nResult lines:\n{result or '(none)'}\nSignals{' (first 150: wave_list finds the others)' if len(names) > 150 else ''}:\n" + "\n".join(shown)
                + f"\nRead it with wave_values / wave_find (dump='{did}'); cite '{did}' in the evidence of your verdict.")

    def _vcd(self, dump: str) -> Path | None:
        r = self.runs.get(dump.strip().upper())
        return Path(r["vcd"]) if r else None

    def list(self, dump: str, pattern: str) -> str:
        from q3tui.eda import vcd

        p = self._vcd(dump)
        if p is None:
            return self._unknown(dump)
        found = vcd.find_vars(vcd.header(p), pattern or ".")
        return "\n".join(f"{v.name} [{v.width}]" for v in found[:200]) + (f"\n… {len(found) - 200} more" if len(found) > 200 else "") if found else f"no signal matches '{pattern}'"

    def values(self, dump: str, signals: list[str], start_ns: float = 0.0, end_ns: float | None = None, max_changes: int = 60) -> str:
        from q3tui.eda import vcd

        p = self._vcd(dump)
        if p is None:
            return self._unknown(dump)
        return vcd.values(p, [s for s in signals if s.strip()], start_ns, end_ns, max(1, min(int(max_changes), 400)))

    def find(self, dump: str, signal: str, value: str, after_ns: float = 0.0, nth: int = 1) -> str:
        from q3tui.eda import vcd

        p = self._vcd(dump)
        if p is None:
            return self._unknown(dump)
        return vcd.find(p, signal, value, after_ns, nth)

    def _unknown(self, dump: str) -> str:
        return f"no dump '{dump}' in this triage" + (f": {', '.join(self.runs)}" if self.runs else ": run sim_probe first")

    def cites(self, evidence: str) -> list[str]:
        """The dumps of this triage the evidence names."""
        return [d for d in dict.fromkeys(re.findall(r"\bD\d+\b", evidence or "", re.I)) if d.upper() in self.runs]

    def sdk_tools(self) -> list:
        import anyio
        from q3tui.llm.tooldef import tool

        @tool("sim_probe", "Run one failing test again with a waveform dump of the instances you name (hierarchical instance paths from the testbench top, "
                           "e.g. tb_top.u_dut.u_core.u_alu; `depth` 1: the signals of those instances, 0: everything below them; `until_ns`: stop the run there). "
                           "Returns the test's result lines, the dump's id (D1, D2, …) and its signal names.",
              {"type": "object", "properties": {"test": {"type": "string"}, "scopes": _STR_LIST, "depth": {"type": "integer"}, "until_ns": {"type": "number"}},
               "required": ["test", "scopes"]})
        async def probe_tool(args: dict) -> dict:
            return _text(await anyio.to_thread.run_sync(lambda: self.run(str(args.get("test", "")), list(args.get("scopes") or []),
                                                                         int(args.get("depth", 1) or 0), args.get("until_ns"))))

        @tool("wave_list", "The signals of a dump whose name matches `pattern` (a regular expression or a substring), with their widths.",
              {"type": "object", "properties": {"dump": {"type": "string"}, "pattern": {"type": "string"}}, "required": ["dump", "pattern"]})
        async def list_tool(args: dict) -> dict:
            return _text(self.list(str(args.get("dump", "")), str(args.get("pattern", ""))))

        @tool("wave_values", "The values of signals in a dump: each one's value at start_ns, then its changes (time in ns: value) up to end_ns. A signal is its full name "
                             "or the end of it (u_alu.o_result). Vectors in hex.",
              {"type": "object", "properties": {"dump": {"type": "string"}, "signals": _STR_LIST, "start_ns": {"type": "number"}, "end_ns": {"type": "number"},
                                                "max_changes": {"type": "integer"}}, "required": ["dump", "signals"]})
        async def values_tool(args: dict) -> dict:
            return _text(await anyio.to_thread.run_sync(lambda: self.values(str(args.get("dump", "")), list(args.get("signals") or []),
                                                                            float(args.get("start_ns") or 0), args.get("end_ns"), int(args.get("max_changes") or 60))))

        @tool("wave_find", "When a signal of a dump takes a value (1, 0, 0x1f, …): the nth time after after_ns.",
              {"type": "object", "properties": {"dump": {"type": "string"}, "signal": {"type": "string"}, "value": {"type": "string"},
                                                "after_ns": {"type": "number"}, "nth": {"type": "integer"}}, "required": ["dump", "signal", "value"]})
        async def find_tool(args: dict) -> dict:
            return _text(await anyio.to_thread.run_sync(lambda: self.find(str(args.get("dump", "")), str(args.get("signal", "")), str(args.get("value", "")),
                                                                          float(args.get("after_ns") or 0), int(args.get("nth") or 1))))

        return [probe_tool, list_tool, values_tool, find_tool]


def for_triage(project, tools, work: Path, kind: str, tests: set[str]) -> Probe | None:
    """The probe of a triage, or None when the `wave` role is not configured / not found (the triage then judges from the files and logs alone).
    Plain testbench only: a UVM test runs with a seed this triage does not have."""
    from q3tui.eda.tools import available

    if kind != "plain" or ROLE not in tools.roles or not available(tools, ROLE):
        return None
    return Probe(project, tools, work, lambda tc: {"tc": tc, "top": "tb_top", "workdir": work, "project": project.root}, tests)
