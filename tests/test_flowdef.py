"""spec/flow.md: lookup, params and gates in effect, conditions, placeholders, sections, the graph, the checks."""

from pathlib import Path

import pytest

from q3tui.config import ConfigLayers
from q3tui.flowdef import Lookup, load_flow
from q3tui.flowdef import text as T

Q3CORE = Path(__file__).resolve().parents[2] / "VLSIT_Q3CORE_ASIC_AI_FLOW"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def flow_file(root: Path, stages: str, overrides: str = "") -> None:
    write(root / "flows/f/FLOW.md", f"---\nname: f\ndescription: a flow\nversion: 1.0.0\nstages: {stages}\n{overrides}---\n")


def stage_file(root: Path, name: str, steps: str, params: str = "", body: str = "") -> None:
    write(root / f"stages/{name}/STAGE.md",
          f"---\nname: {name}\ndescription: a stage\nversion: 1.0.0\n{params}steps: {steps}\n---\n{body}")


def step_file(root: Path, name: str, front: str = "", body: str = "") -> None:
    write(root / f"steps/{name}/STEP.md", f"---\nname: {name}\ndescription: a step\nversion: 1.0.0\n{front}---\n{body}")


def problems(flow) -> list[str]:
    return [p.message for p in flow.problems]


@pytest.fixture
def root(tmp_path):
    return tmp_path / "home"


# -- text -------------------------------------------------------------------------------------------


def test_sections_only_named_markers():
    body = "<!-- note -->\n<!-- draft -->\nwrite {x} and {{y}}\n<!-- /draft -->\n"
    secs, bad = T.sections(body, {"draft"})
    assert secs == {"draft": "write {x} and {{y}}"} and not bad
    _, bad = T.sections("<!-- draft -->\nno end", {"draft"})
    assert bad == ["section `draft` is not closed"]


def test_fill_keeps_single_braces():
    assert T.fill("a {b} {{c}}", {"c": 1}) == "a {b} 1"
    with pytest.raises(KeyError):
        T.fill("{{c}}", {})


@pytest.mark.parametrize("cond,expected", [
    ("target == 'fpga'", True),
    ("target != fpga", False),
    ("target in [asic, fpga]", True),
    ("not lint and target == fpga", True),
    ("lint or (target == asic)", False),
    ("target", True),
])
def test_conditions(cond, expected):
    assert T.evaluate(cond, {"target": "fpga", "lint": False}) is expected


def test_condition_on_unknown_param():
    assert T.check_condition("mode == x", {"target"}) == ["`mode` is not a param"]


# -- loading ----------------------------------------------------------------------------------------


@pytest.mark.skipif(not (Q3CORE / "flows/vlsit/FLOW.md").is_file(), reason="Q3CORE is not next to this repo")
def test_vlsit_flow_of_q3core_loads():
    flow = load_flow("vlsit", Lookup(None, Q3CORE))
    assert flow.ok, "\n".join(map(str, flow.problems))
    assert [s.name for s in flow.stages] == ["spec", "rtl", "verification", "sanity", "synthesis"]
    assert flow.instances["spec"].gate == "manual"
    assert "sdc" not in flow.stage_of("fpga_port").steps  # dropped in synthesis
    assert all(i.definition_hash for i in flow.instances.values())


def test_project_folder_wins_over_home(tmp_path, root):
    proj = tmp_path / "proj" / ".q3tui"
    flow_file(root, "[s]")
    stage_file(root, "s", "[a]")
    step_file(root, "a", "gate: auto\n")
    step_file(proj, "a", "gate: manual\n")
    flow = load_flow("f", Lookup(proj, root))
    assert flow.ok and flow.instances["a"].gate == "manual"


def test_unknown_flow_lists_the_known_ones(root):
    flow_file(root, "[]")
    flow = load_flow("nope", Lookup(None, root))
    assert problems(flow) == ["no flow `nope` (flows: f)"]


def test_params_in_effect_and_placeholders(tmp_path, root):
    flow_file(root, "[{use: s, params: {target: fpga}}]", "overrides: {a: {with: {depth: 4}}}\n")
    stage_file(root, "s", "[{use: a, with: {target: '{{target}}', lib: '{{lib}}'}}]",
               "params:\n  target: {type: enum, values: [asic, fpga], default: asic}\n  lib: {type: str}\n")
    step_file(root, "a", "params:\n  target: {type: str, default: asic}\n  lib: {type: str, default: base}\n"
              "  depth: {type: int, default: 2}\n  width: {type: int, default: 8}\n"
              "outputs:\n  - {artifact: 'net_{{target}}', path: 'out/{{target}}.v'}\n")
    cfg_file = write(tmp_path / "config.yaml", "steps:\n  a:\n    params: {width: 16}\n")
    flow = load_flow("f", Lookup(None, root), ConfigLayers(None, cfg_file))
    assert flow.ok, problems(flow)
    a = flow.instances["a"]
    # an unset stage param leaves the step's own default
    assert a.params == {"target": "fpga", "lib": "base", "depth": 4, "width": 16}
    assert a.outputs[0].artifact == "net_fpga" and a.outputs[0].path == "out/fpga.v"


def test_bad_param_values(root):
    flow_file(root, "[{use: s, params: {target: gpu}}]")
    stage_file(root, "s", "[{use: a, with: {n: x}}]",
               "params:\n  target: {type: enum, values: [asic, fpga], default: asic}\n")
    step_file(root, "a", "params:\n  n: {type: int, default: 1}\n  m: {type: str, required: true}\n")
    msgs = problems(load_flow("f", Lookup(None, root)))
    assert "stage param `target`: `gpu` is not one of ['asic', 'fpga']" in msgs
    assert "STAGE `with`: param `n` `'x'` is not a int" in msgs
    assert "instance `a`: param `m` is required and has no value" in msgs


def test_when_and_drop(root):
    flow_file(root, "[{use: s, params: {lint: false}, drop: [b]}]")
    stage_file(root, "s", "[a, b, {use: c, when: lint}]", "params:\n  lint: {type: bool, default: true}\n")
    for n in "abc":
        step_file(root, n)
    flow = load_flow("f", Lookup(None, root))
    assert flow.ok and flow.stages[0].steps == ["a"]


def test_gate_order(tmp_path, root):
    flow_file(root, "[s]", "overrides: {b: {gate: unattended}}\n")
    stage_file(root, "s", "[a, b, {use: c, gate: manual}]")
    for n in "abc":
        step_file(root, n)
    flow = load_flow("f", Lookup(None, root))
    assert [flow.instances[n].gate for n in "abc"] == ["auto", "unattended", "manual"]
    cfg = write(tmp_path / "config.yaml", "pipeline: {gate_mode: manual}\nsteps: {a: {gate: auto}}\n")
    flow = load_flow("f", Lookup(None, root), ConfigLayers(None, cfg))
    assert [flow.instances[n].gate for n in "abc"] == ["auto", "manual", "manual"]


def test_tasks_need_sections_and_a_system_prompt(root):
    flow_file(root, "[s]")
    stage_file(root, "s", "[a]")
    step_file(root, "a", "tasks:\n  - {name: draft}\n  - {name: review}\n", "<!-- draft -->\nWrite it.\n<!-- /draft -->\n")
    msgs = problems(load_flow("f", Lookup(None, root)))
    assert "task `review` has no section `<!-- review -->` in the body" in msgs
    assert "a step of this stage has tasks: the body needs a `SYSTEM PROMPT` section" in msgs
    stage_file(root, "s", "[a]", body="<!-- SYSTEM PROMPT -->\nYou are.\n<!-- /SYSTEM PROMPT -->\n")
    step_file(root, "a", "tasks:\n  - {name: draft}\n", "<!-- draft -->\nWrite it.\n<!-- /draft -->\n")
    flow = load_flow("f", Lookup(None, root))
    assert flow.ok and flow.stages[0].system_prompt == "You are."
    assert flow.instances["a"].tasks[0].prompt == "Write it."


def test_graph(root):
    flow_file(root, "[s, t]")
    stage_file(root, "s", "[a, b]")
    stage_file(root, "t", "[c]")
    step_file(root, "a", "outputs:\n  - {artifact: x, path: x.txt}\nreceives: [x_issue]\n")
    step_file(root, "b", "outputs:\n  - {artifact: x, mode: update}\n")
    step_file(root, "c", "inputs:\n  - {artifact: x}\n  - {artifact: user_doc, path: doc.md}\nhandback: [x_issue]\n")
    flow = load_flow("f", Lookup(None, root))
    assert flow.ok, problems(flow)
    assert flow.producers == {"x": "a"} and flow.updaters == {"x": ["b"]}
    assert flow.instances["b"].deps == {"a"}
    assert flow.instances["c"].deps == {"a", "b"}
    assert flow.downstream("a") == {"b", "c"}


def test_graph_problems(root):
    flow_file(root, "[s]")
    stage_file(root, "s", "[a, b]")
    step_file(root, "a", "inputs:\n  - {artifact: y}\noutputs:\n  - {artifact: x, path: x.txt}\nhandback: [k]\n")
    step_file(root, "b", "outputs:\n  - {artifact: x, path: x2.txt}\n  - {artifact: y, path: y.txt}\n")
    msgs = problems(load_flow("f", Lookup(None, root)))
    assert "artifact `x` is also created by `a`" in msgs
    assert "handback `k`: no step of the flow receives it" in msgs
    assert "`a` needs `b`, listed after it in stage `s`" in msgs


def test_front_matter_checks(root):
    flow_file(root, "[s]")
    stage_file(root, "s", "[a, {use: a}]")
    step_file(root, "a", "colour: red\nllm_tools: [Write, Bash]\nquestions: [design_choice]\n")
    write(root / "steps/a/STEP.md", (root / "steps/a/STEP.md").read_text().replace("version: 1.0.0", "version: 1.0"))
    msgs = problems(load_flow("f", Lookup(None, root)))
    assert "unknown key `colour`" in msgs
    assert "`version` `1.0` is not MAJOR.MINOR.PATCH" in msgs
    assert "llm tool `Bash` is not one of ['Read', 'Grep', 'Glob', 'Write', 'Edit']" in msgs
    assert "`Write` or `Edit` needs `write`" in msgs
    assert "`design_choice` is built in: it is not listed in `questions`" in msgs
    assert "instance id `a` is used twice in the flow (give one of them `as`)" in msgs


def test_definition_hash_follows_the_step_and_its_stage(root):
    flow_file(root, "[s]")
    stage_file(root, "s", "[a, b]")
    step_file(root, "a")
    step_file(root, "b")
    before = {k: i.definition_hash for k, i in load_flow("f", Lookup(None, root)).instances.items()}
    write(root / "steps/a/notes.md", "more")
    after = {k: i.definition_hash for k, i in load_flow("f", Lookup(None, root)).instances.items()}
    assert before["a"] != after["a"] and before["b"] == after["b"]
