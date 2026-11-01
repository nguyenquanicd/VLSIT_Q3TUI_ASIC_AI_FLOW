"""Events: a fixed list of kinds, each with its declared fields (spec/engine.md "Events"). Every front end and
`events.jsonl` read the same events."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

KINDS: dict[str, tuple[str, ...]] = {
    "definition_changed": ("steps",),
    "run_started": ("scope", "steps"),
    "run_finished": ("outcomes", "cost_usd"),
    "stage_started": (),
    "stage_finished": ("outcome", "reason"),
    "step_started": ("changes", "regenerate"),
    "step_finished": ("result", "cost_usd", "outputs", "error"),
    "step_skipped": ("reason",),
    "task_started": ("task", "model"),
    "task_text": ("task", "text"),
    "tool_call": ("task", "tool", "input"),
    "task_finished": ("task", "cost_usd", "turns", "error"),
    "task_progress": ("task", "thinking_tokens"),
    "approval_waiting": ("open_questions", "files"),
    "approval_resolved": ("decision", "by", "accepted_defaults", "text"),
    "questions": ("open", "ids"),
    "question_answered": ("id", "status", "by"),
    "loop_round": ("round", "problems", "sent_to"),
    "loop_stopped": ("reason", "best_round"),
    "log": ("message",),
    "warning": ("message",),
    "error": ("message",),
    "sdk": ("message",),
}
NOT_WRITTEN = {"task_progress"}  # delivered to the front ends only
FILE_ONLY = {"sdk"}  # written to events.jsonl only


@dataclass
class Event:
    kind: str
    run_id: str = ""
    stage: str = ""
    step: str = ""
    fields: dict = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now().isoformat(timespec="milliseconds"))

    def to_dict(self) -> dict:
        return {"ts": self.ts, "kind": self.kind, "run_id": self.run_id, "stage": self.stage, "step": self.step,
                **self.fields}

    def __getitem__(self, key: str):
        return self.fields[key]


class EventBus:
    """Delivers events to the subscribers and appends them to `events.jsonl`."""

    def __init__(self, file: Path | None):
        self.file = file
        self.subscribers: list[Callable[[Event], None]] = []

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        self.subscribers.append(fn)
        return lambda: self.subscribers.remove(fn)

    def emit(self, kind: str, *, run_id: str = "", stage: str = "", step: str = "", **fields) -> Event:
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind}")
        unknown = set(fields) - set(KINDS[kind])
        if unknown:
            raise ValueError(f"event {kind}: unknown fields {sorted(unknown)}")
        event = Event(kind, run_id, stage, step, {k: fields.get(k) for k in KINDS[kind]})
        if self.file is not None and kind not in NOT_WRITTEN:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with self.file.open("a") as f:
                f.write(json.dumps(event.to_dict(), default=str) + "\n")
        if kind not in FILE_ONLY:
            for fn in list(self.subscribers):
                fn(event)
        return event


def read_events(file: Path) -> list[dict]:
    if not file.is_file():
        return []
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]
