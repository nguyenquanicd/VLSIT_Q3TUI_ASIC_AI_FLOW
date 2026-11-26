"""Mutation testing of the plain testbench (rule VER-11 of the reference flow: a testbench SHOULD be shown able to fail).

On a copy of the RTL (`build/sim/mutate/<id>/rtl`, never `src/rtl`) one bug that matches a requirement is injected per mutant (a rule not applied, a signal
stuck, a phase one cycle late, …), the testbench is compiled with it (tool role `sim`) and the tests that passed on the real RTL run on it (role `run`):
the tests of the mutant's requirements first, then the others, until one fails. Caught: a test failed (or timed out) — the check that caught it is
recorded. Survived: every test passed: a missing check or stimulus, or a mutant equivalent to the original (the survivor review decides). A mutant
that does not compile is never counted as caught. Score = caught / (compiled − equivalent), overall and per requirement (threshold `tb.mutation_threshold`).

The mutants are data (`Mutant`: a file and an exact text replacement), written by an LLM that sees the spec, the requirements and the RTL, never the
testbench (a bug chosen to dodge or to fit the tests would measure nothing); code checks, applies and runs them. Models here (importable: the step
module is loaded from its file)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Mutant(BaseModel):
    id: str = Field("", description='"M-001", … (keep the ids of the mutants you keep; "" for new ones)')
    req_ids: list[str] = Field(default_factory=list, description="The requirements this bug breaks")
    kind: str = Field("", description="rule_not_applied | stuck_signal | late_by_one_cycle | early_by_one_cycle | off_by_one | wrong_reset_value | wrong_priority | "
                                      "wrong_extension | missing_condition | wrong_operator | other")
    description: str = Field(description="The bug in spec terms: which behaviour of the DUT is now wrong, and how (what a test would see)")
    file: str = Field(description="The RTL file to change, project-relative (one of the files listed)")
    find: str = Field(description="Text of that file to replace, copied exactly (whitespace included); it must occur exactly once")
    replace: str = Field(description="The replacement: the buggy code. It must compile and must change the DUT's behaviour")


class MutantPlan(BaseModel):
    mutants: list[Mutant]


class SurvivorVerdict(BaseModel):
    mutant_id: str
    verdict: Literal["equivalent", "missed", "unsure"] = Field(description=(
        "equivalent: no behaviour the spec defines differs (e.g. a change in a don't-care, an unreachable state); missed: the spec-visible behaviour "
        "differs and no test sees it; unsure: you cannot tell"))
    reason: str = Field(description="Why: for equivalent, why no observable behaviour changes; for missed, what behaviour differs and why the tests miss it")
    tc_id: str = Field("", description="missed: the existing test case that should catch it (its requirements), or empty when a new test case is needed")
    request: str = Field("", description=(
        "missed: what the testbench must add, in spec terms only (the stimulus and the check: ports, values, cycles the spec defines) — the testbench "
        "never sees the RTL, so never name an RTL signal, module or line"))


class SurvivorReview(BaseModel):
    verdicts: list[SurvivorVerdict] = Field(default_factory=list)


# -- code ----------------------------------------------------------------------------------------------------------

def key(m: dict) -> str:
    """A mutant's identity (its file and its edit): a result is reused only for the same edit on the same sources."""
    return hashlib.sha256(f"{m['file']}\0{m['find']}\0{m['replace']}".encode()).hexdigest()[:16]


def problem(m: dict, project_root: Path, rtl: list[Path]) -> str | None:
    """Why a mutant cannot be applied (None: it can)."""
    path = (project_root / m["file"]).resolve()
    if path not in rtl:
        return f"{m['file']} is not one of the RTL files"
    if not m["find"]:
        return "empty `find`"
    if m["find"] == m["replace"]:
        return "`replace` is the same as `find`: no bug"
    n = path.read_text(errors="replace").count(m["find"])
    if n != 1:
        return f"`find` occurs {n} times in {m['file']} (it must occur exactly once)"
    return None


def normalize(mutants: list[Mutant], known_reqs: set[str], keep: list[dict], project_root: Path, rtl: list[Path]) -> tuple[list[dict], list[dict]]:
    """(the valid mutants numbered after the kept ones, the rejected ones with their reason). A duplicate of a kept edit is dropped."""
    used = {m["id"] for m in keep}
    seen = {key(m) for m in keep}
    top = max([int(i.split("-")[-1]) for i in used if i.split("-")[-1].isdigit()] + [0])
    ok, bad = [], []
    for raw in mutants:
        m = raw.model_dump()
        m["file"] = m["file"].strip().lstrip("./") if not Path(m["file"]).is_absolute() else m["file"]
        try:
            m["file"] = str((project_root / m["file"]).resolve().relative_to(project_root.resolve()))
        except ValueError:
            pass
        m["req_ids"] = [r for r in m["req_ids"] if r in known_reqs]
        why = problem(m, project_root, rtl)
        if why is None and key(m) in seen:
            why = "the same edit as another mutant"
        if why is not None:
            bad.append({**m, "problem": why})
            continue
        seen.add(key(m))
        if not m["id"] or m["id"] in used:
            top += 1
            m["id"] = f"M-{top:03d}"
        used.add(m["id"])
        ok.append(m)
    return ok, bad


def still_valid(keep: list[dict], project_root: Path, rtl: list[Path]) -> list[dict]:
    """The mutants of an earlier run that still apply to the RTL as it is now."""
    return [m for m in keep if problem(m, project_root, rtl) is None]


def make_copy(work: Path, project_root: Path, rtl_dir: Path, rtl: list[Path], m: dict) -> list[Path]:
    """Copy the RTL into `work/rtl` with the mutant applied; returns the RTL file list of the copy (files outside the RTL folder are used as they are)."""
    dst = work / "rtl"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(rtl_dir, dst)
    target = (project_root / m["file"]).resolve()
    out = []
    for p in rtl:
        try:
            q = dst / p.relative_to(rtl_dir.resolve())
        except ValueError:
            q = p
        if p == target:
            q.write_text(p.read_text(errors="replace").replace(m["find"], m["replace"], 1))
        out.append(q)
    return out


def filelist(work: Path, tb_dir: Path, rtl: list[Path]) -> Path:
    f = work / "filelist_tb_abs.f"
    f.write_text("\n".join(str(p.resolve()) for p in rtl) + f"\n+incdir+{tb_dir.resolve()}\n{(tb_dir / 'tb_top.sv').resolve()}\n")
    return f


def order_tests(m: dict, tests: list[dict]) -> list[dict]:
    """The tests of the mutant's requirements first, then the others (any test that fails catches it)."""
    reqs = set(m.get("req_ids") or [])
    return [t for t in tests if reqs & set(t.get("req_ids") or [])] + [t for t in tests if not reqs & set(t.get("req_ids") or [])]


def score(mutants: list[dict], results: dict[str, dict], equivalent: set[str], threshold: float) -> dict:
    """Overall and per requirement: caught / (compiled − equivalent). A mutant that did not compile, could not run or is equivalent does not count."""
    def counts(ms: list[dict]) -> dict:
        rs = [results.get(m["id"]) or {} for m in ms]
        compiled = [m for m, r in zip(ms, rs) if r.get("status") in ("caught", "survived")]
        eq = [m for m in compiled if m["id"] in equivalent]
        caught = [m for m in compiled if (results[m["id"]]["status"] == "caught")]
        base = len(compiled) - len(eq)
        return {"mutants": len(ms), "compiled": len(compiled), "caught": len(caught), "equivalent": len(eq),
                "survived": base - len(caught), "score": round(len(caught) / base, 3) if base else None}

    total = counts(mutants)
    per_req: dict[str, dict] = {}
    for r in sorted({r for m in mutants for r in m.get("req_ids") or []}):
        c = counts([m for m in mutants if r in (m.get("req_ids") or [])])
        c["status"] = "n/a" if c["score"] is None else "pass" if c["score"] >= threshold else "below"
        per_req[r] = c
    return {"threshold": threshold, **total, "per_req": per_req,
            "above_threshold": sum(c["status"] == "pass" for c in per_req.values()),
            "below_threshold": sum(c["status"] == "below" for c in per_req.values()),
            "na": sum(c["status"] == "n/a" for c in per_req.values())}


def run_mutant(tools, project, lay, m: dict, tests: list[dict], rtl: list[Path], stop=None) -> dict:
    """Compile the testbench with one mutant and run the tests on it until one fails. Never touches src/rtl or src/tb's deliverables."""
    from q3tui.eda.tools import broken, run_role
    from q3tui.flows.dv.plain.simulate import judge

    work = lay.sim / "mutate" / m["id"]
    work.mkdir(parents=True, exist_ok=True)
    files = make_copy(work, project.root, lay.rtl.resolve(), rtl, m)
    fl = filelist(work, lay.tb, files)
    res = run_role(tools, "sim", work, {"filelist": fl, "top": "tb_top", "files": [str(f) for f in files], "incdirs": [f"+incdir+{lay.tb.resolve()}"],
                                        "workdir": work, "project": project.root}, log_name="compile.log")
    if bad := broken(res, "sim"):
        return {"status": "error", "note": bad}
    if not res.ok or res.errors:
        first = next((d.message for d in res.errors), "") or f"rc={res.returncode}"
        return {"status": "not_compiled", "note": first[:300], "log": project.rel(Path(res.log_path)) if res.log_path else ""}
    ok_codes = list(tools.roles["run"].ok_returncodes)
    ran = []
    for t in order_tests(m, tests):
        tc = t["tc_id"]
        r = run_role(tools, "run", work, {"tc": tc, "top": "tb_top", "workdir": work, "project": project.root}, log_name=f"run_{tc}.log", stop=stop)
        if getattr(r, "stopped", False):
            return {"status": "not_run", "note": "stopped", "ran": ran}
        ran.append(tc)
        if r.timed_out:
            return {"status": "caught", "by": tc, "check": "timeout (the mutant hung the test)", "ran": ran}
        if bad := broken(r, "run"):
            return {"status": "error", "note": bad, "ran": ran}
        text = Path(r.log_path).read_text(errors="replace") if r.log_path and Path(r.log_path).is_file() else ""
        status, note = judge(text, r.returncode, ok_codes, tc)
        if status != "PASS":
            return {"status": "caught", "by": tc, "check": note[:300], "ran": ran}
    return {"status": "survived", "ran": ran}
