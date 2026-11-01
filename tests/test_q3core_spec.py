"""The stage `spec` of the Q3CORE flow `vlsit` end to end, with its real step code and a fake LLM."""

import json
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from q3tui.llm import runtime as llm
from q3tui.runtime.session import open_project

Q3CORE = Path(__file__).resolve().parents[2] / "VLSIT_Q3CORE_ASIC_AI_FLOW"
pytestmark = pytest.mark.skipif(not (Q3CORE / "flows/vlsit/FLOW.md").is_file(), reason="Q3CORE is not next to this repo")


def spec_reply() -> str:
    import yaml

    tpl = yaml.safe_load((Q3CORE / "templates/spec/vlsit.yaml").read_text())
    out = ["# FIFO specification", "", "Top module: `m_fifo`", ""]
    for n, s in enumerate(tpl["sections"], 1):
        out += [f"<!-- section: {s['id']} -->", f"## {n}. {s['title']}", ""]
        fields = s.get("fields") or []
        if fields:
            out += ["| | |", "|---|---|"] + [f"| **{f['name'] if isinstance(f, dict) else f}** | N/A — not used |"
                                              for f in fields] + [""]
        out += [f"The FIFO {s['title'].lower()} is as the intent says.", ""]
    out += ["## Open questions", "",
            "- Q: Should the FIFO be first-word fall-through? | assumed: no | blocking: no | kind: design_choice",
            "  - option: no | means: standard read latency | impact: none",
            "  - option: yes | means: data valid with empty low | impact: area +1 register"]
    return "\n".join(out) + "\n"


PARSED = {
    "ip_name": "fifo", "spec_revision": "0.1", "top_module": "m_fifo", "description": "A synchronous FIFO",
    "requirements": [{"id": "", "text": f"The FIFO shall do thing {n}.", "category": "functional",
                      "ambiguity_score": 0.1, "parameters_affected": ["PARA_DEPTH"], "rtl_modules": ["m_fifo"]}
                     for n in range(12)],
    "parameters": [{"name": "PARA_DEPTH", "type": "int", "default": "16", "valid_range": "2..1024",
                    "description": "Depth", "locked": False}],
    "constraints": [{"id": "C1", "rule": "PARA_DEPTH >= 2", "description": "at least two entries"}],
    "modules": [{"name": "m_fifo", "description": "the top", "instances": []}],
    "questions": [], "summary": "12 requirements",
}


def fake_llm(calls):
    def reply(prompt):
        if "Reply with the complete specification as Markdown" in prompt:
            return spec_reply(), None
        if "Review and improve this draft" in prompt:
            return "ok", {"sections": [], "questions": [], "summary": "fine"}
        return "ok", PARSED  # parse_spec

    def query(*, prompt, options):
        calls.append((prompt, options))
        text, structured = reply(prompt)

        async def gen():
            yield AssistantMessage([TextBlock(text)], "m")
            yield ResultMessage("success", 1, 1, False, 1, f"s{len(calls)}", total_cost_usd=0.01, result=text,
                                structured_output=structured)

        return gen()

    return query


async def test_spec_stage(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "query", fake_llm(calls))
    proj = tmp_path / "proj"
    (proj / "spec").mkdir(parents=True)
    (proj / "spec/intent.md").write_text("A 16-deep synchronous FIFO.\n")
    (proj / ".q3tui").mkdir()
    (proj / ".q3tui/config.yaml").write_text("pipeline: {auto_confirm_reviews: true}\n")
    opened = open_project(proj, home=Q3CORE)
    assert not opened.problems, opened.problems
    ops = opened.ops
    res = await ops.run(stage="spec")
    spec = ops.status("spec")
    assert spec.display == "approval waiting", spec.reason
    text = (proj / "spec/spec.md").read_text()
    assert "Top module: `m_fifo`" in text and "<!-- section: purpose_scope -->" in text
    basis = json.loads((proj / "spec/spec.basis.json").read_text())
    assert basis["intent"] == "A 16-deep synchronous FIFO.\n" and basis["template"]["name"] == "vlsit"
    q = ops.engine.decisions.open_of("spec")
    assert any("first-word fall-through" in x.text for x in q)
    assert {o.stage: o.outcome for o in res}["spec"] == "waiting"
    ops.approve("spec")
    await ops.run(stage="spec")
    assert ops.status("parse").display == "approval waiting", ops.status("parse").reason
    req = json.loads((proj / "schemas/structured_spec.json").read_text())
    assert [r["req_id"] for r in req["requirements"]][:2] == ["REQ-001", "REQ-002"]
    assert (proj / "schemas/structured_spec.md").read_text().startswith("# Requirements — fifo")
    ops.approve("parse")
    res = await ops.run(stage="spec")
    assert ops.status("config").display == "done", ops.status("config").reason
    cfg = json.loads((proj / "schemas/final_config.json").read_text())
    assert cfg["parameters"]["PARA_DEPTH"]["value"] == "16" and cfg["constraints"]["C1"]["pass"] is True
    assert {o.stage: o.outcome for o in res}["spec"] == "complete"
    # a change request on config: the overrides task turns it into a value
    ops.request_change("config", "make the FIFO 32 deep")
    monkeypatch.setattr(llm, "query", _overrides_llm(calls))
    await ops.run(only="config")
    cfg = json.loads((proj / "schemas/final_config.json").read_text())
    assert cfg["parameters"]["PARA_DEPTH"]["value"] == "32" and cfg["parameters"]["PARA_DEPTH"]["changed_from_default"]


def _overrides_llm(calls):
    def query(*, prompt, options):
        calls.append((prompt, options))
        out = {"overrides": [{"name": "PARA_DEPTH", "value": "32", "reason": "you asked"}], "style_rules": [],
               "judgements": [], "notes": ""}

        async def gen():
            yield ResultMessage("success", 1, 1, False, 1, "c1", total_cost_usd=0.0, result="", structured_output=out)

        return gen()

    return query
