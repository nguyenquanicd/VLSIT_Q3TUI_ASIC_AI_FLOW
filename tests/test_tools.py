"""spec/tools.md: the tools' environment is made once when Q3TUI loads; a role is available when its program is
found in it; a project's setup_script runs only once allowed."""

from pathlib import Path

from q3tui.config import ConfigLayers
from q3tui.config.schema import Config
from q3tui.engine import Engine, Ops
from q3tui.flowdef import Lookup, load_flow
from q3tui.tools.roles import NOT_APPROVED, ToolEnv
from q3tui.workspace import Project


def write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)
    return path


def setup(tmp: Path) -> Path:
    """A setup script that puts a fake `vcs` on the PATH and counts how often it is sourced."""
    write(tmp / "eda/bin/vcs", "#!/bin/sh\nexit 0\n", 0o755)
    return write(tmp / "eda/setup.sh", f'echo x >> {tmp}/sourced\nexport PATH="{tmp}/eda/bin:$PATH"\n')


def config(tools: dict) -> Config:
    return Config.model_validate({"tools": tools})


def test_loaded_once_and_found(tmp_path):
    script = setup(tmp_path)
    env = ToolEnv(config({"setup_script": str(script), "roles": {"sim": {"cmd": "vcs -full64 {top}"},
                                                                    "lint": {"cmd": "verible-lint {f}"}}}))
    assert env.available("sim") is None
    assert env.available("sim") is None
    assert env.env("sim")["PATH"].startswith(f"{tmp_path}/eda/bin")
    assert env.available("lint") == "`verible-lint` (tool role `lint`) is not found"
    assert env.available("synth") == "the tool role `synth` is not configured (tools.roles.synth)"
    assert (tmp_path / "sourced").read_text().count("x") == 1  # once, not per check or per run


def test_reloaded_when_tools_change(tmp_path):
    script = setup(tmp_path)
    cfg = config({"setup_script": str(script), "roles": {"sim": {"cmd": "vcs"}}})
    env = ToolEnv(cfg)
    env.ensure()
    env.ensure(cfg)
    env.ensure(config({"setup_script": str(script), "timeout_s": 5, "roles": {"sim": {"cmd": "vcs"}}}))
    assert (tmp_path / "sourced").read_text().count("x") == 2


def test_failing_setup(tmp_path):
    script = write(tmp_path / "bad.sh", "echo 'backend unreachable' >&2\nexit 3\n")
    env = ToolEnv(config({"setup_script": str(script), "roles": {"sim": {"cmd": "vcs"}}}))
    assert "failed: backend unreachable" in env.available("sim")


def test_not_approved(tmp_path):
    script = setup(tmp_path)
    env = ToolEnv(config({"setup_script": str(script), "roles": {"sim": {"cmd": "vcs"}}}), approved=lambda c: False)
    assert env.available("sim") == f"the tool role `sim`: {NOT_APPROVED}"
    assert not (tmp_path / "sourced").exists()


def test_project_setup_needs_allow(tmp_path):
    script = setup(tmp_path)
    home = tmp_path / "home"
    project = Project.open(tmp_path / "proj")
    write(project.config_file, f"tools:\n  setup_script: {script}\n  roles:\n    sim: {{cmd: vcs}}\n")
    write(home / "flows/f/FLOW.md", "---\nname: f\ndescription: d\nversion: 1.0.0\nstages: [s]\n---\n")
    write(home / "stages/s/STAGE.md", "---\nname: s\ndescription: d\nversion: 1.0.0\nsteps: [a]\n---\n")
    write(home / "steps/a/STEP.md", "---\nname: a\ndescription: d\nversion: 1.0.0\ntools:\n  - {role: sim}\n"
          "outputs:\n  - {artifact: a, path: a.txt}\n---\n")
    cfg = ConfigLayers(None, project.config_file)
    lookup = Lookup(project.q3, home)
    eng = Engine(project, load_flow("f", lookup, cfg), cfg, lookup)
    ops = Ops(eng, home=home)
    st = eng.status("a")
    assert st.display == "missing_input" and NOT_APPROVED in st.reason
    ops.allow("command", str(script))
    assert eng.status("a").display == "pending"
