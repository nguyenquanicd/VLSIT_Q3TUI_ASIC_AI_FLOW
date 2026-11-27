"""Test plan of the VLSIT testbench: models the LLM returns, normalisation and REQ coverage (code)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from q3tui.steps.common import Question


# The scenario kinds of the verification matrix (general: any IP). A row of a test's case table is one of them; the matrix asks for
# normal / boundary / error per function, reset and stress per group, idle per control, live_change per setting the spec lets change while
# the DUT runs, a random part per random domain and a combined test per pair of groups that share a resource.
ROW_KINDS = ("normal", "boundary", "error", "reset", "idle", "live_change", "stress", "interaction")
FUNCTION_KINDS = ("normal", "boundary", "error")
GROUP_KINDS = ("reset", "stress")


LATER_FIELDS = ("group", "with_groups", "rows", "random")  # (added after plans existed: empty, they do not change a test's hash)


class TbRow(BaseModel):
    id: str = Field("", description='Short case id inside the test, unique in it: "c1", "c2", … ("" = numbered by code)')
    function: str = Field(description="The function of the inventory this case exercises (exactly its inventory name); for idle / live_change: the control or setting")
    kind: str = Field("normal", json_schema_extra={"enum": list(ROW_KINDS)}, description=(
        "Random stimulus is not a case kind: it is the test's `random` part. "
        "normal (typical legal use) | boundary (0, 1, max, max+1, wrap, full / empty, first / last) | error (illegal / unsupported input, "
        "protocol violation, the error the spec defines) | reset (reset while this is in progress: what the spec says survives / clears) | "
        "idle (the control off: the DUT must do nothing, with the other settings non-default) | live_change (the setting written while the DUT "
        "runs: the new value takes effect as the spec says) | stress (back-to-back, maximum rate, long run) | interaction (with another group's "
        "activity at the same time)"))
    stimulus: str = Field("", description="One line: the input of this case")
    expect: str = Field("", description="One line: what the DUT must show, as the spec says it (no number the spec does not give)")


class TbRandom(BaseModel):
    domain: str = Field(description="The random domain of the group it draws from (exactly its name in the group's `random_domains`)")
    oracle: str = Field(description="How each random case is checked: a reference model written from the spec, or a self-check (read back, round trip, invariant)")
    count: int = Field(100, ge=1, description="Random cases per run by default (a plusarg raises it for a stress run)")


class TbCase(BaseModel):
    tc_id: str = Field("", description='Test case id "TC-001", "TC-002", … (keep the ids of unchanged test cases; "" for new ones)')
    group: str = Field("", description="The group of the plan this test belongs to (its `name`)")
    with_groups: list[str] = Field(default_factory=list, description="Other groups this test runs at the same time (a combined test of groups that share a resource)")
    rows: list[TbRow] = Field(default_factory=list, description=(
        "The directed cases this test runs, a table: one row per function × scenario kind it covers. One test = one scenario and one setup; it "
        "runs every row (a failing row does not stop the others)"))
    random: TbRandom | None = Field(None, description="The random part, when the test also runs random legal cases from a seed (null: directed only)")
    name: str = Field(description="lower_snake_case name of the test, e.g. reset_boot_addr")
    description: str = Field("", description="One line: what is stimulated and what is checked")
    req_ids: list[str] = Field(default_factory=list, description=(
        "REQ ids this test case checks: only ids of the task's requirement list (labels written in the spec text are not these ids)"))
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


class TbNA(BaseModel):
    function: str = Field("", description='The function, control, setting, random domain or other group the cell is about ("" = the group as a whole)')
    kind: str = Field(description="The scenario kind (normal, boundary, error, reset, idle, live_change, stress, random, interaction)")
    reason: str = Field(description="Why no test needs it, from the spec (e.g. 'no illegal input: every 4-bit value is a defined command')")


class TbGroup(BaseModel):
    name: str = Field(description="lower_snake_case group name, e.g. fifo_flags, apb_access, vector_load_store")
    title: str = Field("", description="One line: what the group verifies")
    req_ids: list[str] = Field(default_factory=list, description="The requirements of the group (every requirement planned for is in exactly one group)")
    controls: list[str] = Field(default_factory=list, description="Enables / modes that switch part of the group off: each needs an idle case (off: the DUT does nothing)")
    live_settings: list[str] = Field(default_factory=list, description="Settings the spec lets change while the DUT runs: each needs a live_change case (empty when the spec allows none)")
    random_domains: list[str] = Field(default_factory=list, description=(
        "Large stimulus spaces worth random cases, short names (an instruction set, an address / data range, a command / transaction sequence): "
        "each needs a test with a random part and its oracle"))
    shares: list[str] = Field(default_factory=list, description="Resources this group uses that others use too (a bus, an interrupt line, a buffer, a pipeline, a register file): a pair of groups sharing one needs a combined test")
    not_applicable: list[TbNA] = Field(default_factory=list, description="Matrix cells no test needs, each with its spec reason (usually few)")


class TbMatrix(BaseModel):
    """The first stage of a plan: what must be tested, before any test case (the verification matrix)."""
    inventory: list[ReqFunctions] = Field(default_factory=list, description="For every requirement planned for: its functions (each instruction, register / field, mode, error case)")
    groups: list[TbGroup] = Field(default_factory=list, description="The groups of the plan: every requirement planned for in exactly one")
    excluded: list[TbExcluded] = Field(default_factory=list, description="Requirements no simulation of the DUT can check, each with its reason")
    questions: list[Question] = Field(default_factory=list, description="Questions found (usually none)")


class TbGroupPlan(BaseModel):
    """The test cases of one group (the second stage: one batch per group)."""
    test_cases: list[TbCase] = Field(default_factory=list, description=(
        "The group's tests: new ones (tc_id \"\") and changed ones (their tc_id, the whole row). Unchanged tests are not repeated"))
    not_applicable: list[TbNA] = Field(default_factory=list, description="Matrix cells of this group no test needs, each with its spec reason")
    excluded: list[TbExcluded] = Field(default_factory=list, description="A requirement of the group no simulation can check (usually none)")
    questions: list[Question] = Field(default_factory=list, description="Questions found (usually none)")


class TbPlan(BaseModel):
    groups: list[TbGroup] = Field(default_factory=list, description="The groups of the plan (usually made by the matrix stage; a whole plan may restate them)")
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
    groups: list[TbGroup] = Field(default_factory=list, description=(
        "Only new groups and changed ones (by name, the whole group as it should be); the others stay"))
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
        rows, w_rows = _rows(tid, c.rows)
        warnings.extend(w_rows)
        funcs = list(dict.fromkeys([*(f.strip() for f in c.functions if f.strip()), *(r.function for r in rows if r.kind not in ("idle", "live_change"))]))
        group = fn_key(c.group)
        out.append(c.model_copy(update={"tc_id": tid, "name": name, "req_ids": ok, "failure_modes": fms, "test_type": kind, "functions": funcs,
                                        "group": group, "with_groups": [g for g in dict.fromkeys(fn_key(x) for x in c.with_groups) if g and g != group],
                                        "rows": rows}))
    return out, warnings


def _rows(tid: str, rows: list[TbRow]) -> tuple[list[TbRow], list[str]]:
    """Row ids unique in the test ("c1", "c2", …), kinds known (an unknown one is normal, with a warning)."""
    out, warnings, used = [], [], set()
    for r in rows:
        kind = fn_key(r.kind)
        if kind not in ROW_KINDS:
            warnings.append(f"{tid}: case kind '{r.kind}' unknown (one of {', '.join(ROW_KINDS)}): taken as normal")
            kind = "normal"
        rid = re.sub(r"[^A-Za-z0-9_]+", "_", r.id).strip("_")
        if not rid or rid in used:
            n = len(used) + 1
            while f"c{n}" in used:
                n += 1
            rid = f"c{n}"
        used.add(rid)
        out.append(r.model_copy(update={"id": rid, "kind": kind, "function": r.function.strip()}))
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


def normalize_groups(groups: list[TbGroup], known_reqs: set[str]) -> tuple[list[dict], list[str]]:
    """Group names file-safe and unique, unknown REQ ids dropped, a requirement in one group only (the first that names it)."""
    out: dict[str, dict] = {}
    seen: dict[str, str] = {}
    warnings = []
    for g in groups:
        name = fn_key(g.name) or f"group_{len(out) + 1}"
        reqs = []
        for r in g.req_ids:
            if r not in known_reqs:
                warnings.append(f"group {name}: unknown requirement id {r} dropped")
            elif r in seen and seen[r] != name:
                warnings.append(f"{r} is in groups {seen[r]} and {name}: kept in {seen[r]}")
            elif r not in reqs:
                reqs.append(r)
                seen[r] = name
        d = g.model_dump()
        d.update({"name": name, "req_ids": reqs, "not_applicable": [n for n in d["not_applicable"] if n.get("reason", "").strip()]})
        if name in out:  # (the same group twice: merged)
            o = out[name]
            for k in ("req_ids", "controls", "live_settings", "random_domains", "shares"):
                o[k] = list(dict.fromkeys([*o[k], *d[k]]))
            o["not_applicable"] += d["not_applicable"]
        else:
            out[name] = d
    return list(out.values()), warnings


def merge_groups(old: list[dict], new: list[dict]) -> list[dict]:
    """A patch's groups replace the ones with their name; the others stay. A requirement moved to a new group leaves its old one."""
    named = {g["name"]: g for g in new}
    moved = {r for g in new for r in g["req_ids"]}
    out = [named.pop(g["name"], None) or {**g, "req_ids": [r for r in g["req_ids"] if r not in moved]} for g in old]
    return out + list(named.values())


def add_not_applicable(groups: list[dict], group: str, entries: list[TbNA]) -> None:
    """A batch's `not_applicable` cells go to its group (only those with a reason)."""
    g = next((g for g in groups if g["name"] == group), None)
    if g is None:
        return
    have = {(fn_key(n["function"]), fn_key(n["kind"])) for n in g["not_applicable"]}
    for e in entries:
        k = (fn_key(e.function), fn_key(e.kind))
        if e.reason.strip() and k not in have:
            g["not_applicable"].append(e.model_dump())
            have.add(k)


def matrix(cases: list[dict], groups: list[dict], inventory: list[dict], excluded: set[str]) -> list[dict]:
    """The verification matrix by code: per group, every cell (function × normal / boundary / error, the group's reset and stress, idle per
    control, live_change per live setting, random per random domain, interaction per pair of groups sharing a resource) with its status:
    covered (the tests that cover it), na (the reason) or missing. A cell is covered by any test's row of that function and kind (any group:
    a function another group's test runs is run); the group's own cells (reset, stress, random, interaction) by the group's tests."""
    funcs = {r["req_id"]: r["functions"] for r in inventory}
    rows: dict[tuple[str, str], list[str]] = {}
    for c in cases:
        for r in c.get("rows") or []:
            rows.setdefault((fn_key(r["function"]), r["kind"]), []).append(c["tc_id"])

    def of_group(g: str) -> list[dict]:
        return [c for c in cases if c.get("group") == g or g in (c.get("with_groups") or [])]

    share: dict[str, set[str]] = {}
    for g in groups:
        for s in g.get("shares") or []:
            share.setdefault(fn_key(s), set()).add(g["name"])
    pairs: dict[str, dict[str, str]] = {}
    for res, gs in share.items():
        for a in gs:
            for b in gs:
                if a < b:
                    pairs.setdefault(a, {}).setdefault(b, res)
    out = []
    for g in groups:
        name = g["name"]
        na = {(fn_key(n["function"]), fn_key(n["kind"])): n["reason"] for n in g.get("not_applicable") or []}
        mine = of_group(name)
        cells: list[dict] = []

        def cell(function: str, kind: str, by: list[str]) -> None:
            key = (fn_key(function), kind)
            if by:
                cells.append({"function": function, "kind": kind, "status": "covered", "by": sorted(set(by))})
            elif key in na or (fn_key(function), "") in na:
                cells.append({"function": function, "kind": kind, "status": "na", "reason": na.get(key) or na[(fn_key(function), "")]})
            else:
                cells.append({"function": function, "kind": kind, "status": "missing"})

        for rid in g["req_ids"]:
            if rid in excluded:
                continue
            for f in funcs.get(rid, []):
                for k in FUNCTION_KINDS:
                    cell(f, k, rows.get((fn_key(f), k), []))
        for k in GROUP_KINDS:
            cell("", k, [c["tc_id"] for c in mine if any(r["kind"] == k for r in c.get("rows") or [])
                         or (k == "stress" and c.get("test_type") == "stress")])
        for ctl in g.get("controls") or []:
            cell(ctl, "idle", rows.get((fn_key(ctl), "idle"), []))
        for s in g.get("live_settings") or []:
            cell(s, "live_change", rows.get((fn_key(s), "live_change"), []))
        for d in g.get("random_domains") or []:
            cell(d, "random", [c["tc_id"] for c in mine if c.get("random") and fn_key(c["random"].get("domain", "")) == fn_key(d)])
        for other, res in (pairs.get(name) or {}).items():
            by = [c["tc_id"] for c in cases if {name, other} <= {c.get("group"), *(c.get("with_groups") or [])}]
            cell(other, "interaction", by)
            cells[-1]["shared"] = res
        out.append({"group": name, "title": g.get("title", ""), "req_ids": g["req_ids"], "cells": cells})
    return out


def matrix_gaps(mat: list[dict]) -> dict[str, list[str]]:
    """group -> its missing cells, one line each ('lw: boundary', 'reset', 'idle: irq_enable', 'interaction with apb_access (shares apb)')."""
    out: dict[str, list[str]] = {}
    for g in mat:
        miss = []
        for c in g["cells"]:
            if c["status"] != "missing":
                continue
            if c["kind"] == "interaction":
                miss.append(f"interaction with {c['function']} (shares {c.get('shared', '?')})")
            else:
                miss.append(f"{c['function']}: {c['kind']}" if c["function"] else c["kind"])
        if miss:
            out[g["group"]] = miss
    return out


def matrix_summary(mat: list[dict]) -> dict:
    n = lambda s: sum(c["status"] == s for g in mat for c in g["cells"])  # noqa: E731
    return {"cells": sum(len(g["cells"]) for g in mat), "covered": n("covered"), "na": n("na"), "missing": n("missing")}


REVIEW_ROWS = 400  # case rows per plan reviewer (rv32iv: 1459 rows in one review read 1.7M tokens in 6 turns)


def review_chunks(cases: list[dict], ids: set[str], rows: int = REVIEW_ROWS) -> list[set[str]]:
    """The tests to review (`ids`) split for parallel reviewers: whole groups together, in the plan's order, about `rows` case rows each
    (a group larger than that is split)."""
    order: dict[str, list[dict]] = {}
    for c in cases:
        if c["tc_id"] in ids:
            order.setdefault(c.get("group") or "", []).append(c)
    out: list[set[str]] = []
    cur: set[str] = set()
    n = 0
    for tests in order.values():
        size = sum(1 + len(c.get("rows") or []) for c in tests)
        if cur and n + size > rows:  # (a group that does not fit starts a new reviewer)
            out.append(cur)
            cur, n = set(), 0
        for c in tests:
            w = 1 + len(c.get("rows") or [])
            if cur and n + w > rows:
                out.append(cur)
                cur, n = set(), 0
            cur.add(c["tc_id"])
            n += w
    if cur:
        out.append(cur)
    return out


def ungrouped(groups: list[dict], known_reqs: set[str], excluded: set[str]) -> list[str]:
    """Requirements planned for (not excluded) that no group has."""
    have = {r for g in groups for r in g["req_ids"]}
    return sorted(r for r in known_reqs if r not in have and r not in excluded)


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
    rows = (c.get("rows") if isinstance(c, dict) else [r.model_dump() for r in c.rows]) or []
    absent = [r for r in rows if not re.search(rf'`TC_CASE\(\s*"{re.escape(r["id"])}"', text)]
    if absent:
        out.append("planned case(s) without their `TC_CASE(\"<id>\") before their stimulus: "
                   + "; ".join(f"{r['id']} ({r['function']}: {r['kind']})" for r in absent[:12]) + (" …" if len(absent) > 12 else ""))
    rnd = c.get("random") if isinstance(c, dict) else (c.random.model_dump() if c.random else None)
    if rnd and not ("`TC_SEED" in text and "tc_rand_n(" in text):
        out.append("the planned random part needs its seed logged with `TC_SEED(seed) and its case count from tc_rand_n(<default>)")
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
