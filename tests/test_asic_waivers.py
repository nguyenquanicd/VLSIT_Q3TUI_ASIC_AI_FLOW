"""Waivers of the ASIC synthesis report (q3tui/flows/asic/lib/waivers.py, docs/spec/asic-flow.md "Waivers")."""

from pathlib import Path

import pytest

from q3tui.core.project import Project
from q3tui.flows.asic.lib import dc, waivers

REPORT = """****************************************
Report : constraint
        -all_violators
****************************************
   min_delay/hold ('i_clk_core' group)

                             Required        Actual
   Endpoint                 Path Delay     Path Delay        Slack
   -----------------------------------------------------------------
   u_mem_r0_c0/WEB              0.06           0.01 r        -0.06  (VIOLATED)
   u_mem_r0_c0/D[0]             0.05           0.00 r        -0.03  (VIOLATED)

   max_transition

                             Required        Actual
   Net                      Transition     Transition        Slack
   -----------------------------------------------------------------
   n123                         0.20           0.25          -0.05  (VIOLATED)

   min_capacitance
   o_ld_rd_data[0]              0.00           0.00           0.00  (VIOLATED: increase significant digits)
"""
LOG = "Warning: In design 'top', port 'a[0]' is not connected to any nets. (LINT-28)\nWarning: x (LINT-28)\nWarning: y (VER-318)\n"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "q3tui.yaml").write_text("pipeline:\n  flow: asic\n")
    return Project.open(tmp_path)


def test_the_violations_keep_their_group():
    items = dc.violation_items(REPORT)
    assert [(i["group"], i["slack_ns"]) for i in items] == [("min_delay/hold", -0.06), ("min_delay/hold", -0.03), ("max_transition", -0.05)]
    assert len(items) == len(dc.violations(REPORT))  # (the rounding-only min_capacitance line is no violation)
    assert waivers.endpoint(items[0]) == "u_mem_r0_c0/WEB"


def test_a_group_waiver_covers_up_to_its_cap_and_an_item_one_violation(project):
    items, codes = dc.violation_items(REPORT), waivers.warning_codes(LOG)
    assert {c: v["count"] for c, v in codes.items()} == {"LINT-28": 2, "VER-318": 1}
    waivers.add(project, "group", "min_delay/hold", "fixed in physical design", 0.06)
    waivers.add(project, "code", "LINT-28", "unused address bits")
    open_, waived, open_codes, waived_codes = waivers.apply(waivers.load(project), items, codes)
    assert [i["group"] for i in open_] == ["max_transition"] and len(waived) == 2
    assert list(open_codes) == ["VER-318"] and list(waived_codes) == ["LINT-28"]
    # a smaller cap: the worse violation is open again; one violation can be waived by itself
    waivers.add(project, "group", "min_delay/hold", "fixed in physical design", 0.04)
    waivers.add(project, "item", "max_transition:n123", "a test net")
    open_, *_ = waivers.apply(waivers.load(project), items, codes)
    assert [waivers.endpoint(i) for i in open_] == ["u_mem_r0_c0/WEB"]
    assert len([w for w in waivers.load(project) if w["key"] == "min_delay/hold"]) == 1  # (waiving again replaces)
    waivers.remove(project, "min_delay/hold")
    assert {w["key"] for w in waivers.load(project)} == {"LINT-28", "max_transition:n123"}
    with pytest.raises(ValueError):
        waivers.remove(project, "nothing")
    assert waivers.path(project) == Path(project.reviews_dir) / "asic_synth_waivers.json"


def test_the_report_rows_are_groups_and_codes():
    data = {"groups_violated": {"min_delay/hold": {"count": 713, "open": 0, "worst_ns": -0.06, "sample": "u/WEB"}},
            "warnings": {"LINT-28": {"count": 188, "sample": "x"}, "VER-318": {"count": 47, "sample": "y", "waived": True}}}
    rows = {r["key"]: r for r in waivers.report_items(data)}
    assert rows["min_delay/hold"]["what"] == "group" and rows["min_delay/hold"]["open"] == 0
    assert rows["LINT-28"]["open"] == 188 and rows["VER-318"]["open"] == 0


def test_a_run_before_waivers_is_read_from_its_reports(project):
    rep = project.build_dir / "syn" / "asic" / "reports"
    rep.mkdir(parents=True)
    (rep / "constraints.rpt").write_text(REPORT)
    (project.root / "dc.out").write_text(LOG)
    waivers.add(project, "code", "VER-318", "fine")
    rows = {r["key"]: r for r in waivers.report_items(waivers.from_reports(project, {"log": "dc.out"}))}
    assert rows["min_delay/hold"]["count"] == 2 and rows["min_delay/hold"]["worst_ns"] == -0.06 and rows["min_delay/hold"]["open"] == 2
    assert rows["max_transition"]["open"] == 1 and rows["LINT-28"]["open"] == 2 and rows["VER-318"]["open"] == 0
