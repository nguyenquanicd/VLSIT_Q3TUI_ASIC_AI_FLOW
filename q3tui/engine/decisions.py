"""The questions, their answers and their history, in `.q3tui/decisions.yaml`, committed with the project
(spec/engine.md "Questions")."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from q3tui.engine.state import now

STATUSES = ("open", "answered", "defaulted", "dropped")
LOOP_OPTIONS = ("fix_again", "other_input", "accept")


@dataclass
class Question:
    id: str
    key: str
    step: str  # the step that asked
    kind: str
    text: str
    blocking: bool = False
    default: str | None = None
    options: list[dict] = field(default_factory=list)  # {text, impact}
    status: str = "open"
    answer: str | None = None
    by: str | None = None  # you | auto
    at: str | None = None
    owner: str | None = None  # the step the answer went to
    problem: dict | None = None  # a question of a stopped fix loop: {kind, unit, key, checker, receiver}
    history: list[dict] = field(default_factory=list)

    @property
    def settled(self) -> bool:
        return self.status in ("answered", "defaulted")


class Decisions:
    def __init__(self, file: Path):
        self.file = file
        self.questions: list[Question] = []
        if file.is_file():
            data = yaml.safe_load(file.read_text()) or {}
            self.questions = [Question(**q) for q in data.get("questions") or []]

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        data = {"questions": [{k: v for k, v in asdict(q).items() if v not in (None, [], {})} for q in self.questions]}
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        os.replace(tmp, self.file)

    # -- lookups --------------------------------------------------------------------------------

    def get(self, qid: str) -> Question | None:
        return next((q for q in self.questions if q.id == qid), None)

    def by_key(self, key: str) -> Question | None:
        return next((q for q in self.questions if q.key == key), None)

    def of_step(self, step: str, status: str | None = None) -> list[Question]:
        return [q for q in self.questions if q.step == step and (status is None or q.status == status)]

    def open_of(self, step: str, *, blocking: bool | None = None) -> list[Question]:
        return [q for q in self.of_step(step, "open") if blocking is None or q.blocking == blocking]

    def next_id(self, step: str) -> str:
        pat = re.compile(rf"^{re.escape(step)}-Q(\d+)$")
        n = max((int(m.group(1)) for q in self.questions if (m := pat.match(q.id))), default=0)
        return f"{step}-Q{n + 1}"

    # -- changes --------------------------------------------------------------------------------

    def ask(self, step: str, kind: str, key: str, text: str, default, options, blocking: bool,
            problem: dict | None = None) -> Question:
        """A question asked again with the same key is the same question: it keeps its id and its answer."""
        q = self.by_key(key)
        if q is not None:
            q.text, q.kind, q.blocking, q.options = text, kind, blocking, list(options or [])
            q.default = None if default is None else str(default)
            if q.status == "dropped":
                q.history.append({"status": "dropped", "at": q.at})
                q.status, q.answer, q.by, q.at = "open", None, None, None
            q.step = step
            q.problem = problem or q.problem
            return q
        q = Question(self.next_id(step), key, step, kind, text, blocking, None if default is None else str(default),
                     list(options or []), problem=problem)
        self.questions.append(q)
        return q

    def settle(self, q: Question, status: str, answer, by: str) -> None:
        if q.answer is not None or q.status != "open":
            q.history.append({"status": q.status, "answer": q.answer, "by": q.by, "at": q.at})
        q.status, q.answer, q.by, q.at = status, None if answer is None else str(answer), by, now()

    def drop(self, q: Question) -> None:
        q.status = "dropped"
        q.at = now()

    def clear_step(self, step: str) -> None:
        self.questions = [q for q in self.questions if q.step != step]
