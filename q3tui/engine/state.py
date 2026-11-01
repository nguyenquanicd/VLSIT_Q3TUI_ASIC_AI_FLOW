"""`.q3tui/state/pipeline.json`: the recorded state of each step and the cost (spec/workspace.md), and the lock
between processes (spec/engine.md "Operations")."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

RESULTS = ("pending", "running", "done", "stale", "failed", "missing_input")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Approval:
    status: str  # waiting | approved
    by: str | None = None  # you | auto
    at: str | None = None


@dataclass
class Request:
    """A change request on a step: from you, from a decision, or a problem handed back (`fix`)."""

    id: int
    source: str  # you | decision | fix
    text: str
    unit: str | None = None
    kind: str | None = None
    key: str | None = None
    question: str | None = None  # the question a decision answers
    status: str = "pending"  # pending | delivered
    at: str = field(default_factory=now)


@dataclass
class Loop:
    """The fix loop whose checking step is this one."""

    round: int = 0  # rounds sent since the counter went back to 0
    last: list[list[str]] | None = None  # the problems of the last round, [kind, unit, key]
    best: dict | None = None  # {round, count}
    accepted: list[list[str]] = field(default_factory=list)  # [kind, unit, key]
    pending: list[dict] = field(default_factory=list)  # problems not sent yet (waiting for the gate)
    stopped: bool = False


@dataclass
class StepState:
    result: str = "pending"  # pending | running | done | failed | missing_input (stale is worked out)
    reason: str = ""
    origin: str = "generated"  # generated | user
    inputs: dict[str, str] = field(default_factory=dict)  # each hashed thing -> its hash
    params: dict = field(default_factory=dict)  # the values of its `affects_result` params when it ran
    hash: str = ""  # the combined hash of `inputs`
    outputs: dict[str, str] = field(default_factory=dict)  # artifact -> hash, as the step left it
    definition: dict = field(default_factory=dict)  # {hash, version, files, later}
    approval: Approval | None = None
    requests: list[Request] = field(default_factory=list)
    reviews: dict[str, dict] = field(default_factory=dict)  # artifact -> {item: {hash, status}}
    loop: Loop = field(default_factory=Loop)
    tools: dict[str, dict] = field(default_factory=dict)  # role -> the last result (for `tool` checks)
    cost_usd: float = 0.0
    started: dict | None = None  # {backup, before}: to put back an interrupted step
    finished_at: str | None = None
    ran: bool = False

    def pending_requests(self) -> list[Request]:
        return [r for r in self.requests if r.status == "pending"]


@dataclass
class PipelineState:
    steps: dict[str, StepState] = field(default_factory=dict)
    artifacts: dict[str, dict] = field(default_factory=dict)  # artifact -> {hash, by}: the last write by a step
    cost_usd: float = 0.0
    cost_resets: list[dict] = field(default_factory=list)
    next_request: int = 1
    assistant_cost_usd: float = 0.0  # the assistant's cost: not part of a run (pipeline.max_cost)

    def step(self, sid: str) -> StepState:
        return self.steps.setdefault(sid, StepState())

    # -- file -----------------------------------------------------------------------------------

    @classmethod
    def load(cls, file: Path) -> PipelineState:
        if not file.is_file():
            return cls()
        data = json.loads(file.read_text())
        steps = {sid: step_from_dict(d) for sid, d in (data.get("steps") or {}).items()}
        return cls(steps, data.get("artifacts") or {}, float(data.get("cost_usd") or 0.0),
                   list(data.get("cost_resets") or []), int(data.get("next_request") or 1),
                   float(data.get("assistant_cost_usd") or 0.0))

    def save(self, file: Path) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1, default=str))
        os.replace(tmp, file)


def step_from_dict(d: dict) -> StepState:
    d = dict(d)
    d["approval"] = Approval(**d["approval"]) if d.get("approval") else None
    d["requests"] = [Request(**r) for r in d.get("requests") or []]
    d["loop"] = Loop(**(d.get("loop") or {}))
    return StepState(**{k: v for k, v in d.items() if k in StepState.__dataclass_fields__})


class LockError(Exception):
    pass


class Lock:
    """One run per project at a time, between processes; another process can only watch."""

    def __init__(self, file: Path):
        self.file = file
        self.fd: int | None = None

    def acquire(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.file, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise LockError("another Q3TUI is running this project; this one can only watch") from exc
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self.fd = fd

    def release(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    @property
    def held(self) -> bool:
        return self.fd is not None
