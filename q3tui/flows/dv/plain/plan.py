"""Test plan of the VLSIT testbench: models the LLM returns, normalisation and REQ coverage (code)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from q3tui.steps.common import Question


class TbCase(BaseModel):
    tc_id: str = Field("", description='Test case id "TC-001", "TC-002", … (keep the ids of unchanged test cases; "" for new ones)')
    name: str = Field(description="lower_snake_case name of the test, e.g. reset_boot_addr")
    description: str = Field("", description="One line: what is stimulated and what is checked")
    req_ids: list[str] = Field(default_factory=list, description="REQ ids this test case checks")
    conditional_param: str | None = Field(None, description="A top-level parameter that must be enabled for this test to apply (PR_… / PARA_…), else null")
    conditional_value: str | None = Field(None, description="The value it must have (null: any non-zero value)")
    failure_modes: list[str] = Field(default_factory=list, description=(
        "The DUT bugs this test case catches, one sentence each: the bug -> the check that sees it (e.g. 'full flag set one entry late -> the push "
        "after the last free entry is accepted and overwrites the oldest'). Each must be visible on some legal input: a bug that gives the same "
        "outputs as the correct design for every legal input is not a failure mode. A test case that catches no bug is not a test"))
    observe: str = Field("", description="Where the test sees the DUT's result: a port, a value read back from DUT memory, a spec-defined probe")
    test_type: str = Field("directed", description=(
        "directed (fixed stimulus for one function) | combined (features that share a resource, a state machine or a clock domain, together) | "
        "constrained_random (random legal stimulus, a seed, a reference model or self-check) | fault_injection (illegal / error inputs, protocol "
        "violations, reset in the middle) | stress (back-to-back, full / empty, maximum rate, long runs)"))
    functions: list[str] = Field(default_factory=list, description=(
        "The DUT functions this test exercises, short names (e.g. 'lw', 'csr_write', 'uart_tx_frame'): one check per function, so a failure names it"))


class TbFinding(BaseModel):
    tc_id: str = Field("", description="The test case the finding is about (empty: the plan as a whole)")
    rule: str = Field("", description="The tc-quality rule it breaks (Q1 … Q10)")
    severity: str = Field("must", description="must: a check that cannot fail on a real DUT bug, or a planned failure mode with no check; should: a gap that leaves the main bugs caught")
    problem: str = Field(description="What is wrong, concretely: the check / line / value")
    fix: str = Field("", description="How to fix it: the stimulus, the window, the check to add")


class TbReview(BaseModel):
    findings: list[TbFinding] = Field(default_factory=list, description="Test-quality findings (empty when the test cases are fine)")
    questions: list[Question] = Field(default_factory=list, description="Spec points the review found unclear (spec_gap / req_gap); usually none")


class QuestionSweep(BaseModel):
    questions: list[Question] = Field(default_factory=list, description=(
        "Every point the spec leaves open that changes a test's expected value, stimulus or observation, each with its default_assumption and 2-4 "
        "options; a follow-up that depends on the answer is folded into the same question (its options answer the whole branch). Empty when the "
        "spec says enough"))


class TbExcluded(BaseModel):
    req_id: str = Field(description="A REQ id no simulation of the DUT can check")
    reason: str = Field("", description="Why (a goal, a lint / coding rule, a synthesis / SDC / timing constraint, a document, a tool flow, a constraint on the DUT's environment "
                        "that the testbench obeys): said once here, never asked as a question")


class ReqFunctions(BaseModel):
    req_id: str
    functions: list[str] = Field(default_factory=list, description=(
        "Every separately testable function the requirement names or implies, short names: each instruction, each register / field, each mode, "
        "each error case (e.g. a requirement 'the FIFO supports push, pop and flush, with full and empty flags' -> push, pop, flush, full_flag, "
        "empty_flag; one naming an instruction set or a command set -> every instruction / command). A test case that exercises one names it in "
        "its `functions` with exactly this name"))


class TbPlan(BaseModel):
    inventory: list[ReqFunctions] = Field(default_factory=list, description=(
        "First, before the test cases: for every requirement you plan for, the functions it names (its function inventory). Code checks that each one is "
        "exercised by a test case that is not constrained_random (a random test adds depth; it does not replace the directed check of a function)"))
    test_cases: list[TbCase]
    excluded: list[TbExcluded] = Field(default_factory=list, description=(
        "Requirements that cannot be checked by simulating the DUT, each with its reason. They are not uncovered and are not asked about: the user reviews them with the plan"))
    questions: list[Question] = Field(default_factory=list, description=(
        "Questions found while planning (usually none): spec_gap / req_gap (the requirement is wrong or unclear), design_choice"))


class TbRemoved(BaseModel):
    tc_id: str
    reason: str = Field("", description="Why the test case goes (merged into another, its requirement removed, …)")


class TbPlanPatch(BaseModel):
    """An update of the plan: only what changes (the unchanged test cases are kept by code). Every full answer re-sent the whole plan: on rv32iv
    68 test cases, 35–39k output tokens and 3–4 minutes per update call."""
    inventory: list[ReqFunctions] = Field(default_factory=list, description=(
        "Only the requirements whose function list changes, each with its whole new list (the others are kept as they are)"))
    test_cases: list[TbCase] = Field(default_factory=list, description=(
        "Only new test cases (tc_id \"\") and changed ones (their tc_id, the whole row as it should be). Unchanged test cases are NOT repeated: "
        "they stay"))
    removed: list[TbRemoved] = Field(default_factory=list, description="Test cases to delete (tc_id and why); usually none")
    excluded: list[TbExcluded] = Field(default_factory=list, description=(
        "Only requirements newly left out of simulation, with the reason (the ones already excluded stay; a requirement a test case covers is no "
        "longer excluded)"))
    questions: list[Question] = Field(default_factory=list, description=(
        "Questions found while planning (usually none): spec_gap / req_gap (the requirement is wrong or unclear), design_choice"))


def apply_patch(previous: list[dict], changed: list[TbCase], removed: list[str]) -> list[TbCase]:
    """The whole plan after an update: a changed test case replaces the one with its id (in place), a new one is appended, a removed one goes."""
    gone = set(removed)
    by_id = {c.tc_id: c for c in changed if c.tc_id}
    out = [by_id.pop(p["tc_id"], None) or TbCase.model_validate({k: v for k, v in p.items() if k in TbCase.model_fields})
           for p in previous if p["tc_id"] not in gone]
    return out + [c for c in changed if not c.tc_id or c.tc_id in by_id]


def merge_inventory(old: list[dict], new: list[dict]) -> list[dict]:
    """A patch's inventory replaces the lists of the requirements it names; the others stay."""
    named = {r["req_id"]: r for r in new}
    return [named.pop(r["req_id"], r) for r in old] + list(named.values())


class TbUnitResult(BaseModel):
    summary: str = Field("", description="What was written, briefly")
    questions: list[Question] = Field(default_factory=list, description="Questions found while writing (usually none)")


TEST_TYPES = ("directed", "combined", "constrained_random", "fault_injection", "stress")


def tc_number(tc_id: str) -> int:
    m = re.search(r"(\d+)$", tc_id)
    return int(m.group(1)) if m else 0


def normalize(cases: list[TbCase], known_reqs: set[str], previous: list[dict] | None = None) -> tuple[list[TbCase], list[str]]:
    """Ids unique and numbered (new ones continue after the highest), names made file-safe, unknown REQ ids dropped.
    Returns (cases, warnings)."""
    warnings: list[str] = []
    prev_by_name = {p["name"]: p["tc_id"] for p in previous or []}
    used: set[str] = set()
    top = max([tc_number(c.tc_id) for c in cases] + [tc_number(p["tc_id"]) for p in previous or []] + [0])
    out = []
    for c in cases:
        name = re.sub(r"[^a-z0-9]+", "_", c.name.lower()).strip("_") or "test"
        tid = c.tc_id if re.fullmatch(r"TC-\d+", c.tc_id or "") else prev_by_name.get(name, "")
        if not tid or tid in used:
            top += 1
            tid = f"TC-{top:03d}"
        used.add(tid)
        ok = [r for r in c.req_ids if r in known_reqs]
        if len(ok) != len(c.req_ids):
            warnings.append(f"{tid}: unknown requirement id(s) dropped: {', '.join(sorted(set(c.req_ids) - set(ok)))}")
        fms = [" ".join(f.split()) for f in c.failure_modes if f.strip()]
        if not fms:
            warnings.append(f"{tid}: no failure mode: the plan does not say which DUT bug this test case catches")
        kind = (c.test_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        if kind not in TEST_TYPES:
            warnings.append(f"{tid}: unknown test_type '{c.test_type}' (one of {', '.join(TEST_TYPES)}): taken as directed")
            kind = "directed"
        funcs = list(dict.fromkeys(f.strip() for f in c.functions if f.strip()))
        out.append(c.model_copy(update={"tc_id": tid, "name": name, "req_ids": ok, "failure_modes": fms, "test_type": kind, "functions": funcs}))
    return out, warnings


def fn_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def normalize_inventory(inventory: list[ReqFunctions], known_reqs: set[str], old: list[dict] | None = None) -> list[dict]:
    """{req_id, functions} per known requirement (duplicates merged); an answer without an inventory keeps the earlier one."""
    out: dict[str, list[str]] = {}
    for r in inventory:
        if r.req_id in known_reqs:
            have = out.setdefault(r.req_id, [])
            for f in r.functions:
                if f.strip() and fn_key(f) not in {fn_key(x) for x in have}:
                    have.append(f.strip())
    if not out and old:
        return list(old)
    return [{"req_id": k, "functions": v} for k, v in out.items() if v]


def function_gaps(selected: list[dict], inventory: list[dict], excluded: set[str]) -> dict[str, list[str]]:
    """REQ -> the functions of its inventory that no selected test case exercises outside constrained_random (a random test alone is no
    directed check: rv32iv's plan reached lui, auipc and every ALU op only through its random program)."""
    done = {fn_key(f) for c in selected if (c.get("test_type") or "directed") != "constrained_random" for f in c.get("functions") or []}
    gaps = {}
    for r in inventory:
        if r["req_id"] in excluded:
            continue
        miss = [f for f in r["functions"] if fn_key(f) not in done]
        if miss:
            gaps[r["req_id"]] = miss
    return gaps


def plan_warnings(cases: list[dict], reqs: dict[str, str], excluded: set[str]) -> list[str]:
    """What the plan as a whole lacks (the reference flow's tb_generator: warn about requirements and failure modes without tests, plan the
    kinds of test a real regression has). Warnings for the plan's review, never a failure."""
    out = []
    kinds = {c.get("test_type") or "directed" for c in cases}
    if cases and kinds <= {"directed"}:
        out.append("the plan has only directed tests: no constrained_random, combined, fault_injection or stress test "
                   "(a directed-only regression misses the bugs between the planned cases)")
    for k in ("constrained_random", "fault_injection"):
        if cases and k not in kinds and len(cases) >= 6:
            out.append(f"no {k} test in the plan")
    with_fm = {r for c in cases if c.get("failure_modes") for r in c["req_ids"]}
    bare = sorted(r for r in {r for c in cases for r in c["req_ids"]} if r not in with_fm and r not in excluded)
    if bare:
        out.append(f"requirement(s) whose test cases name no failure mode: {', '.join(bare[:12])}{' …' if len(bare) > 12 else ''}")
    return out


def applies(c: TbCase | dict, params: dict[str, str]) -> bool:
    """A conditional test case applies when its parameter has the value (any non-zero value when none is named)."""
    param = c["conditional_param"] if isinstance(c, dict) else c.conditional_param
    value = c.get("conditional_value") if isinstance(c, dict) else c.conditional_value
    if not param:
        return True
    have = params.get(param)
    if have is None:
        return True  # an unknown parameter cannot switch a test off
    if value is not None:
        return _norm(have) == _norm(value)
    return _norm(have) not in ("0", "", "false", "1'b0", "0'b0")


def _norm(v: str) -> str:
    v = str(v).strip().lower().replace("_", "")
    m = re.fullmatch(r"\d*'[bdho]?0+", v)
    return "0" if m else v


def file_name(c: TbCase | dict) -> str:
    tid = c["tc_id"] if isinstance(c, dict) else c.tc_id
    name = c["name"] if isinstance(c, dict) else c.name
    return f"tc_{tc_number(tid):03d}_{name}.sv"


def task_name(c: TbCase | dict) -> str:
    tid = c["tc_id"] if isinstance(c, dict) else c.tc_id
    name = c["name"] if isinstance(c, dict) else c.name
    return f"tc_{tc_number(tid):03d}_{name}"


_ALWAYS_TRUE = re.compile(r"`TC_CHECK\s*\(\s*(?:1'b1|1'h1|1'd1|'1|1|\(1\))\s*,")


def quality_problems(c: TbCase | dict, text: str) -> list[str]:
    """The checks code can make on a test case file (the tc-quality skill): a check that is always true, a planned failure mode without its
    `// FM<k>:` tag (the check that catches it). The rest is the reviewer stage's judgment."""
    fms = c.get("failure_modes") if isinstance(c, dict) else c.failure_modes  # (a plan made before failure modes existed has none)
    out = []
    if _ALWAYS_TRUE.search(text):
        out.append("a `TC_CHECK whose condition is a constant 1: it can never fail (check a value the DUT produced)")
    missing = [k for k in range(1, len(fms or []) + 1) if not re.search(rf"//\s*FM{k}\b", text)]
    if missing:
        out.append("no `// FM<k>:` tag above the check that catches planned failure mode(s) "
                   + "; ".join(f"FM{k} ({fms[k - 1]})" for k in missing))
    return out


def required_reqs(spec: dict) -> dict[str, str]:
    """Requirements a simulation test case is expected to check (static / assumption requirements are SVA-only)."""
    return {r["req_id"]: r.get("text", "") for r in spec.get("requirements", [])
            if r.get("req_id") and r.get("sva_hint") not in ("static", "assume")}


def normalize_excluded(excluded: list[TbExcluded], known_reqs: set[str], covered: set[str]) -> tuple[list[dict], list[str]]:
    """The requirements the planner left out of simulation, as {req_id, reason}: one entry per REQ, unknown ids dropped, and one a test case covers is not excluded."""
    out: dict[str, dict] = {}
    warnings: list[str] = []
    for e in excluded:
        if e.req_id not in known_reqs:
            warnings.append(f"{e.req_id}: unknown requirement id dropped from the requirements left out of simulation")
        elif e.req_id in covered:
            warnings.append(f"{e.req_id}: a test case checks it, so it is not left out of simulation")
        else:
            out[e.req_id] = {"req_id": e.req_id, "reason": e.reason.strip()}
    return list(out.values()), warnings


def coverage(selected: list[TbCase | dict], spec: dict, excluded: set[str] | None = None) -> dict:
    """REQ coverage of the selected test cases. `excluded`: the requirements the planner decided no simulation can check (with a reason): not uncovered."""
    excluded = excluded or set()
    need = {r: t for r, t in required_reqs(spec).items() if r not in excluded}
    covered = sorted({r for c in selected for r in (c["req_ids"] if isinstance(c, dict) else c.req_ids) if r in need})
    uncovered = sorted(set(need) - set(covered))
    return {"total_req_ids": len(need), "covered_req_ids": covered, "uncovered_req_ids": uncovered, "excluded_req_ids": sorted(excluded & set(required_reqs(spec))),
            "coverage_pct": round(100.0 * len(covered) / len(need), 1) if need else 100.0}
