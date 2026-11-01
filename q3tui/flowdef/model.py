"""A flow once loaded: its stages, the instances of its steps, and the graph of its artifacts (spec/flow.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Problem:
    file: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}: {self.message}"


@dataclass
class Param:
    name: str
    type: str
    values: list | None = None
    default: object = None
    required: bool = False
    affects_result: bool = True
    doc: str = ""


@dataclass
class Input:
    artifact: str
    path: str | None = None  # a user file when set
    required: bool = True
    hashed: bool = True
    llm_visible: bool = True


@dataclass
class Output:
    artifact: str
    path: str | None
    mode: str = "create"  # create | update | seed
    user_provided: bool = False
    schema: str | None = None
    excludes: list[str] = field(default_factory=list)
    view: dict | None = None


@dataclass
class Task:
    name: str
    output: str = "markdown"  # a JSON Schema file of the step's folder, markdown or text
    to: str | None = None
    per_unit: bool = False
    prompt: str = ""


@dataclass
class Instance:
    """One use of a step in the flow."""

    id: str
    step: str
    stage: str
    folder: Path
    version: str
    description: str
    params: dict
    param_decls: dict[str, Param]
    gate: str
    inputs: list[Input]
    outputs: list[Output]
    assets: list[str]
    tools: list[dict]  # {role, required (bool, resolved), doc}
    packages: list[dict]
    passes: list[dict]  # {check, on_fail, doc}
    tasks: list[Task]
    questions: list[str]
    answers: list[str]
    handback: list[str]
    receives: list[str]
    llm_tools: list[str]
    mcp_tools: list[str]
    write: list[str]
    skills: list[str]
    units: dict | None
    has_code: bool
    has_addon: bool
    deps: set[str] = field(default_factory=set)  # instance ids it depends on (inputs and its chain)
    chain_prev: str | None = None
    definition_hash: str = ""

    def output(self, artifact: str) -> Output | None:
        return next((o for o in self.outputs if o.artifact == artifact), None)


@dataclass
class Stage:
    name: str
    folder: Path
    params: dict
    steps: list[str]  # instance ids, in chain order
    system_prompt: str | None


@dataclass
class Flow:
    name: str
    description: str
    version: str
    body: str
    stages: list[Stage]
    instances: dict[str, Instance]
    producers: dict[str, str]  # artifact -> the instance that creates it
    updaters: dict[str, list[str]]  # artifact -> instances that update it in place
    answers: dict[str, str]  # question kind -> the instance that answers it
    receivers: dict[str, str]  # problem kind -> the instance that receives it
    problems: list[Problem]
    files: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def order(self) -> list[str]:
        """Every instance id, stage by stage, in chain order."""
        return [sid for st in self.stages for sid in st.steps]

    def stage_of(self, instance_id: str) -> Stage:
        return next(st for st in self.stages if instance_id in st.steps)

    def upstream(self, instance_id: str) -> set[str]:
        """The instances `instance_id` depends on, directly or through others."""
        seen: set[str] = set()
        todo = list(self.instances[instance_id].deps)
        while todo:
            sid = todo.pop()
            if sid not in seen:
                seen.add(sid)
                todo += list(self.instances[sid].deps)
        return seen

    def downstream(self, instance_id: str) -> set[str]:
        return {sid for sid in self.instances if instance_id in self.upstream(sid)}
