"""The verification report of the plain testbench (VER-12 and step 8 of the reference flow's /verification), built by code from the artifacts:
`selected_testplan.json` (the tests: purpose, type, functions, failure modes, quality findings), `test_plan.json` (the requirements left out),
`dv_test_results.json` (the statuses), `dv_triage.json` (whose fault each failure is), `dv_check_activity.json` (the checks that ran),
`dv_mutation.json` (the testbench's strength). Written as `schemas/dv_verification_report.json` and `reports/dv_verification_report.md`.

A requirement is `verified` only when it has a test, every one of its tests passed, every planned failure mode of those tests was checked (its check
ran), and its mutation score is at the threshold (or no mutant was made for it: said so). Missing, not run, N/A, failed and passed stay distinct;
nothing is averaged. An AI review (the quality reviewer, the survivor review) is advisory and is marked so."""

from __future__ import annotations

from q3tui.core.project import read_json, write_json
from q3tui.flows.spec.lib import artifacts

JSON = "dv_verification_report.json"
MD = "dv_verification_report.md"

# the triage's verdict → the failure category of the reference flow's failure_analysis
CATEGORY = {"rtl_bug": "dut", "tb_bug": "testbench", "prepare_bug": "testbench", "spec_issue": "specification", "unsure": "unclassified"}
STATUS_CATEGORY = {"TIMEOUT": "environment", "BLOCKED": "environment", "ERROR": "tool"}


def build(project, lay, mutation: dict | None) -> dict:
    """The report as data (also returned)."""
    plan = artifacts.read(project, "selected_testplan.json") or {}
    tplan = artifacts.read(project, "test_plan.json") or {}
    spec = artifacts.read(project, "structured_spec.json") or {}
    results = read_json(lay.schemas / "dv_test_results.json", default={}) or {}
    triage = read_json(lay.schemas / "dv_triage.json", default={}) or {}
    act = read_json(lay.schemas / "dv_check_activity.json", default={}) or {}
    status = {t["tc_id"]: t for t in results.get("tests") or [] if isinstance(t, dict) and t.get("tc_id")}
    activity = {t["tc_id"]: t for t in act.get("tests") or [] if isinstance(t, dict) and t.get("tc_id")}
    verdicts = {v.get("id"): v for v in triage.get("verdicts") or [] if isinstance(v, dict)}
    first_detail = {f.get("id"): f.get("note", "") for f in triage.get("failures") or [] if isinstance(f, dict)}
    cases = [c for c in plan.get("test_cases") or [] if c.get("selected")]
    reqs = {r["req_id"]: r.get("text", "") for r in spec.get("requirements") or [] if r.get("req_id")}
    excluded = {e["req_id"]: e.get("reason", "") for e in tplan.get("excluded") or [] if e.get("req_id")}

    tc_rows, fa = [], []
    for c in cases:
        tid = c["tc_id"]
        st = (status.get(tid) or {}).get("status") or "NOT_RUN"
        note = (status.get(tid) or {}).get("note") or ""
        a = activity.get(tid) or {}
        v = verdicts.get(tid)
        row = {"tc_id": tid, "name": c.get("name", ""), "purpose": c.get("description", ""), "test_type": c.get("test_type") or "directed",
               "functions": c.get("functions") or [], "req_ids": c.get("req_ids") or [], "status": st, "note": note,
               "checks_run": a.get("checks_run"), "checks_unreached": len(a.get("unreached") or []), "fm_unchecked": a.get("fm_unchecked") or [],
               "seeds": a.get("seeds") or [], "quality_findings": c.get("quality_findings") or [], "group": c.get("group") or "",
               "cases": a.get("cases")}
        if st not in ("PASS", "NOT_RUN", "PENDING"):
            cat = CATEGORY.get((v or {}).get("verdict", ""), STATUS_CATEGORY.get(st, "unclassified"))
            row.update({"failure_category": cat, "cause": (v or {}).get("summary", "") or note, "evidence": (v or {}).get("evidence", "")})
            fa.append({"tc_ids": [tid], "symptom": first_detail.get(tid) or note, "category": cat, "evidence": (v or {}).get("evidence", ""),
                       "cause": (v or {}).get("summary", ""), "action": (v or {}).get("request", "") or ("waits for your decision" if v else "not analysed"),
                       "status": "open", "review": {"reviewer": "ai_agent", "verdict": (v or {}).get("verdict", ""), "advisory": True} if v else None})
        tc_rows.append(row)
    # one failure-analysis row per distinct signature (the same category and symptom)
    merged: dict[tuple, dict] = {}
    for r in fa:
        k = (r["category"], r["symptom"][:120])
        if k in merged:
            merged[k]["tc_ids"] += r["tc_ids"]
        else:
            merged[k] = r
    fa = list(merged.values())

    mut_req = (mutation or {}).get("score", {}).get("per_req", {}) if mutation else {}
    threshold = ((mutation or {}).get("score") or {}).get("threshold")
    cov = []
    for r in sorted(reqs):
        tests = [t for t in tc_rows if r in t["req_ids"]]
        passed = [t for t in tests if t["status"] == "PASS"]
        m = mut_req.get(r)
        if r in excluded:
            state = "excluded"
        elif not tests:
            state = "uncovered"
        elif any(t["status"] in ("FAIL", "TIMEOUT", "ERROR") for t in tests):
            state = "failing"
        elif len(passed) < len(tests):
            state = "not_run"
        elif any(t["fm_unchecked"] for t in tests) or (m and m.get("status") == "below"):
            state = "partial"
        else:
            state = "verified"
        cov.append({"req_id": r, "tests_passed": len(passed), "tests_total": len(tests), "mutation_score": (m or {}).get("score"),
                    "mutants": (m or {}).get("mutants", 0), "status": state})

    not_verified: list[str] = []
    for r, why in sorted(excluded.items()):
        not_verified.append(f"{r}: not simulated — {why or 'no reason given'}")
    not_verified += [f"{c['req_id']}: no test case" for c in cov if c["status"] == "uncovered"]
    for t in tc_rows:
        if t["status"] == "PASS" and t["fm_unchecked"]:
            not_verified.append(f"{t['tc_id']}: passed, but the check of {', '.join(t['fm_unchecked'])} never ran")
        if t["status"] == "PASS" and t["checks_unreached"]:
            not_verified.append(f"{t['tc_id']}: {t['checks_unreached']} check(s) never reached")
        for q in t["quality_findings"]:
            if q.get("severity") == "must":
                not_verified.append(f"{t['tc_id']}: quality review (advisory) — {q.get('problem', '')}")
    if mutation:
        for m in mutation.get("mutants") or []:
            res = (mutation.get("results") or {}).get(m["id"]) or {}
            if res.get("status") == "survived" and m["id"] not in set(mutation.get("equivalent") or []):
                not_verified.append(f"{m['id']} ({', '.join(m.get('req_ids') or []) or 'no REQ'}): a bug no test caught — {m.get('description', '')}")
        not_verified += [f"{r}: mutation score {c['mutation_score']} below {threshold}" for r, c in ((c["req_id"], c) for c in cov) if c["mutation_score"] is not None
                         and threshold is not None and c["mutation_score"] < threshold]
        if mutation.get("status") not in ("done",):
            not_verified.append(f"mutation: {mutation.get('status')} — {mutation.get('note', '')}")
    else:
        not_verified.append("mutation: not run")
    no_mut = [c["req_id"] for c in cov if c["status"] not in ("excluded", "uncovered") and not c["mutants"]]
    if mutation and mutation.get("status") == "done" and no_mut:
        not_verified.append(f"no mutant was made for {len(no_mut)} requirement(s): {', '.join(no_mut[:15])}{' …' if len(no_mut) > 15 else ''} (their strength is not measured)")
    not_verified += ["formal proof: not run by this flow", "code coverage: not measured by this flow"]

    by = lambda key, rows: {k: sum(r.get(key) == k for r in rows) for k in sorted({r.get(key) for r in rows if r.get(key)})}  # noqa: E731
    data = {"metadata": {"ip_name": (plan.get("metadata") or {}).get("ip_name", ""), "at": artifacts.now(),
                         "sources": [project.rel(p) for p in project.spec_documents()], "gate_signoff_approved": False},
            "summary": {"tests": len(tc_rows), "tests_by_status": by("status", tc_rows), "tests_by_type": by("test_type", tc_rows),
                        "open_failures_by_category": by("category", fa),
                        "tests_with_unchecked_failure_modes": sum(bool(t["fm_unchecked"]) for t in tc_rows if t["status"] == "PASS"),
                        "requirements_by_status": by("status", cov),
                        "mutation": ({k: (mutation.get("score") or {}).get(k) for k in ("score", "mutants", "compiled", "caught", "survived", "equivalent",
                                                                                         "threshold", "above_threshold", "below_threshold", "na")}
                                     | {"status": mutation.get("status")}) if mutation else {"status": "not run"}},
            "tc_results": tc_rows, "failure_analysis": fa, "coverage_summary": cov, "not_verified": not_verified}
    return data


def write(project, lay, mutation: dict | None) -> dict:
    data = build(project, lay, mutation)
    write_json(lay.schemas / JSON, data)
    lay.reports.mkdir(parents=True, exist_ok=True)
    (lay.reports / MD).write_text(render(data))
    return data


def _cell(s) -> str:
    return str(s if s not in (None, "") else "–").replace("|", "\\|").replace("\n", " ")


def render(d: dict) -> str:
    s = d["summary"]
    m = s.get("mutation") or {}
    out = [f"# Verification report — {d['metadata'].get('ip_name') or 'DUT'}", "",
           f"Derived from: {', '.join(d['metadata']['sources']) or 'spec/'} (the spec and the requirements are the oracle; the RTL never set an expected value).", "",
           "## Summary", "", "| Item | Value |", "|---|---|",
           f"| Tests by status | {_cell(', '.join(f'{k} {v}' for k, v in s['tests_by_status'].items()))} |",
           f"| Tests by type | {_cell(', '.join(f'{k} {v}' for k, v in s['tests_by_type'].items()))} |",
           f"| Open failures by category | {_cell(', '.join(f'{k} {v}' for k, v in s['open_failures_by_category'].items()) or 'none')} |",
           f"| Passing tests with a failure mode never checked | {s['tests_with_unchecked_failure_modes']} |",
           f"| Requirements | {_cell(', '.join(f'{k} {v}' for k, v in s['requirements_by_status'].items()))} |",
           "| Mutation | " + (_cell(f"score {m.get('score')} (threshold {m.get('threshold')}): {m.get('caught')} caught / {m.get('survived')} survived, "
                                 f"{m.get('equivalent')} equivalent, {(m.get('mutants') or 0) - (m.get('compiled') or 0)} not compiled of {m.get('mutants')}; "
                                 f"requirements at the threshold {m.get('above_threshold')}, below {m.get('below_threshold')}, n/a {m.get('na')}")
                           if m.get("status") == "done" else _cell(m.get("status"))) + " |",
           "", "## Tests", "", "| TC | Name | Group | Type | Functions | REQs | Status | Cases passed | Checks run | Unchecked FMs | Seeds | Cause |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in d["tc_results"]:
        cs = t.get("cases")
        cases = (f"{cs['run'] - cs['failed']}/{cs['run']}" + (f" (failed: {', '.join(cs['failed_ids'][:6])})" if cs["failed_ids"] else "")) if cs else "–"
        out.append(f"| {t['tc_id']} | `{t['name']}` | {_cell(t.get('group') or '–')} | {t['test_type']} | {_cell(', '.join(t['functions']))} | {_cell(', '.join(t['req_ids']))} | "
                   f"{t['status']} | {_cell(cases)} | {_cell(t['checks_run'])} | {_cell(', '.join(f.split(' ')[0] for f in t['fm_unchecked']))} | {_cell(', '.join(map(str, t['seeds'])))} | "
                   f"{_cell(t.get('cause', ''))} |")
    out += ["", "## Failure analysis", ""]
    if d["failure_analysis"]:
        out += ["| Tests | Symptom | Category | Cause | Evidence | Action | Status | Review |", "|---|---|---|---|---|---|---|---|"]
        for r in d["failure_analysis"]:
            rv = r.get("review") or {}
            review = f"AI triage (advisory): {rv.get('verdict')}" if rv else ""
            out.append(f"| {', '.join(r['tc_ids'])} | {_cell(r['symptom'][:200])} | {r['category']} | {_cell(r['cause'])} | {_cell(r['evidence'][:200])} | "
                       f"{_cell(r['action'][:200])} | {r['status']} | {_cell(review)} |")
    else:
        out.append("No failing test.")
    out += ["", "## Coverage per requirement", "", "| REQ | Tests passed | Mutation score | Mutants | Status |", "|---|---|---|---|---|"]
    out += [f"| {c['req_id']} | {c['tests_passed']}/{c['tests_total']} | {_cell(c['mutation_score'])} | {c['mutants']} | {c['status']} |" for c in d["coverage_summary"]]
    out += ["", "## Not verified", ""] + [f"- {x}" for x in d["not_verified"]]
    out += ["", "verified: every test passed, every planned failure mode's check ran, mutation score at the threshold (or no mutant: listed above). "
            "AI reviews are advisory; the sign-off is yours (gate `signoff`).", ""]
    return "\n".join(out)
