"""Opening a project: find it, read the config, load the flow and its addons, and make the engine and Ops that
the TUI (and later the CLI) use."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from q3tui.config import ConfigLayers, ConfigWarning, parse_session_options
from q3tui.engine import Engine, Ops
from q3tui.engine.ops import OPS_ACTIONS
from q3tui.flowdef import Flow, Lookup, Problem, load_flow
from q3tui.llm.runtime import LLMRuntime
from q3tui.paths import q3tui_home
from q3tui.runtime.addons import Addons, load_addons
from q3tui.runtime.code import CodeLoader
from q3tui.runtime.services import StepServices
from q3tui.tools.roles import ToolEnv
from q3tui.tools.run import ToolRunner
from q3tui.workspace import Approvals, Project


@dataclass
class Opened:
    project: Project
    config: ConfigLayers
    lookup: Lookup
    flow: Flow
    addons: Addons
    engine: Engine | None = None  # None while the flow has errors
    ops: Ops | None = None
    problems: list[Problem] = field(default_factory=list)  # the flow's and its addons'

    @property
    def warnings(self) -> list[ConfigWarning]:
        return self.config.warnings


def open_project(start: Path, *, session: list[str] | None = None, home: Path | None = None,
                 flow: str | None = None) -> Opened:
    """Find (or create) the project of `start` and load everything. A config error raises ConfigError (shown before
    the TUI appears); a flow with errors still opens, without an engine, and lists them."""
    home = home or q3tui_home()
    project = Project.open(start)
    config = ConfigLayers(home / "config.yaml", project.config_file, parse_session_options(session or []))
    lookup = Lookup(project.q3, home)
    approvals = Approvals(home / "approvals.yaml")

    def code_approved(path: Path, content: bytes) -> bool:
        return approvals.allowed(project.root, "code", content)

    def command_approved(command: str) -> bool:
        return approvals.allowed(project.root, "command", command)

    loaded = load_flow(flow or config.config.pipeline.flow, lookup, config)
    addons = load_addons(loaded, set(OPS_ACTIONS), project_q3=project.q3, approved=code_approved) if loaded.ok \
        else Addons()
    problems = [*loaded.problems, *addons.problems]
    opened = Opened(project, config, lookup, loaded, addons, problems=problems)
    if problems:
        return opened
    tool_env = ToolEnv(config.config)
    engine = Engine(project, loaded, config, lookup, code_for=CodeLoader(project.q3, code_approved),
                    approvals=approvals, tool_env=tool_env,
                    allow_run=lambda inst, cmd: not inst.folder.is_relative_to(project.q3) or command_approved(cmd))
    tool_env.approved = engine._setup_approved
    tools = ToolRunner(config, tool_env, project.root, project.work_dir, readers=addons.readers,
                       approved=command_approved)
    engine.services = StepServices(LLMRuntime(project, config, approved=command_approved), tools)
    opened.engine = engine
    opened.ops = Ops(engine, home=home)
    opened.ops.addons = addons
    return opened
