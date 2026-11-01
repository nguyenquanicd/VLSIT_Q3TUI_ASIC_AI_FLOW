"""The files of artifacts, their hashes, and the small JSON paths the flow files use (`$.a[*].b`)."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from q3tui.flowdef.model import Flow, Instance

WILDCARD = re.compile(r"[*?\[]")


def is_glob(path: str) -> bool:
    return bool(WILDCARD.search(path))


def expand(path: str, root: Path) -> Path:
    """A path of a param or a user file: absolute, `~`, `$VAR`, or relative to the project root."""
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    return p if p.is_absolute() else root / p


def match(pattern: str, root: Path) -> list[Path]:
    """The files a path names: a file, every file of a folder, or the files a glob matches (`**` included)."""
    base = expand(pattern, root)
    if not is_glob(pattern):
        if base.is_file():
            return [base]
        if base.is_dir():
            return sorted(p for p in base.rglob("*") if p.is_file())
        return []
    return sorted(Path(p) for p in glob.glob(str(base), recursive=True) if Path(p).is_file())


def write_target(pattern: str, root: Path) -> Path:
    """Where an output is written: its file, or for a glob the folder before the first wildcard."""
    if not is_glob(pattern):
        return expand(pattern, root)
    parts = Path(pattern).parts
    head = []
    for part in parts:
        if WILDCARD.search(part):
            break
        head.append(part)
    return expand(str(Path(*head)) if head else ".", root)


def hash_files(files: list[Path], root: Path) -> str:
    """One hash for a set of files (their paths and contents); "" when there is none."""
    if not files:
        return ""
    h = hashlib.sha256()
    for f in sorted(files):
        try:
            rel = str(f.relative_to(root))
        except ValueError:
            rel = str(f)
        h.update(rel.encode() + b"\0")
        h.update(f.read_bytes() + b"\0")
    return h.hexdigest()


def hash_value(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Artifacts:
    """Where each artifact of a flow is on disk."""

    def __init__(self, flow: Flow, root: Path):
        self.flow, self.root = flow, root

    def pattern(self, artifact: str, reader: Instance | None = None) -> str | None:
        """The path of an artifact: its creator's, or the reader's own user-file path."""
        creator = self.flow.producers.get(artifact)
        if creator is not None:
            out = self.flow.instances[creator].output(artifact)
            return out.path if out else None
        if reader is not None:
            for i in reader.inputs:
                if i.artifact == artifact and i.path:
                    return i.path
        for inst in self.flow.instances.values():
            for i in inst.inputs:
                if i.artifact == artifact and i.path:
                    return i.path
        return None

    def files(self, artifact: str, reader: Instance | None = None, _seen: frozenset = frozenset()) -> list[Path]:
        pattern = self.pattern(artifact, reader)
        if pattern is None:
            return []
        files = match(pattern, self.root)
        creator = self.flow.producers.get(artifact)
        out = self.flow.instances[creator].output(artifact) if creator else None
        if out and out.excludes:
            drop: set[Path] = set()
            for ex in out.excludes:
                if ex not in _seen and ex != artifact:
                    drop |= set(self.files(ex, None, _seen | {artifact}))
            files = [f for f in files if f not in drop]
        return files

    def hash(self, artifact: str, reader: Instance | None = None) -> str:
        return hash_files(self.files(artifact, reader), self.root)

    def exists(self, artifact: str, reader: Instance | None = None) -> bool:
        return bool(self.files(artifact, reader))

    def target(self, artifact: str) -> Path | None:
        pattern = self.pattern(artifact)
        return write_target(pattern, self.root) if pattern else None


# -- backups ------------------------------------------------------------------------------------


def backup(files: list[Path], root: Path, dest: Path) -> list[str]:
    """Copy files under `dest`, keeping their path from the project root; returns the paths copied."""
    copied = []
    for f in files:
        try:
            rel = f.relative_to(root)
        except ValueError:
            continue
        target = dest / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        copied.append(str(rel))
    return copied


def restore(dest: Path, root: Path, current: list[Path]) -> None:
    """Put a backup back: the files it holds are restored, the other current files are removed."""
    kept = set()
    base = dest / "files"
    if base.is_dir():
        for f in base.rglob("*"):
            if f.is_file():
                rel = f.relative_to(base)
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, root / rel)
                kept.add((root / rel).resolve())
    for f in current:
        if f.resolve() not in kept and f.is_file():
            f.unlink()


# -- JSON paths ---------------------------------------------------------------------------------

_STEP = re.compile(r"\.([A-Za-z_][\w\-]*)|\[(\*|-?\d+)\]|\[['\"]([^'\"]+)['\"]\]")


def json_path(data, path: str) -> list:
    """The values a small JSON path selects: `$`, `.key`, `['key']`, `[n]`, `[*]`."""
    path = path.strip()
    if not path.startswith("$"):
        raise ValueError(f"a JSON path starts with `$`: {path}")
    rest = path[1:]
    nodes = [data]
    pos = 0
    while pos < len(rest):
        m = _STEP.match(rest, pos)
        if not m:
            raise ValueError(f"cannot read `{rest[pos:]}` in the JSON path {path}")
        pos = m.end()
        name, index, quoted = m.group(1) or m.group(3), m.group(2), None
        nxt = []
        for n in nodes:
            if name is not None or quoted is not None:
                if isinstance(n, dict) and name in n:
                    nxt.append(n[name])
            elif index == "*":
                if isinstance(n, list):
                    nxt.extend(n)
                elif isinstance(n, dict):
                    nxt.extend(n.values())
            else:
                i = int(index)
                if isinstance(n, list) and -len(n) <= i < len(n):
                    nxt.append(n[i])
        nodes = nxt
    return nodes


def read_json(files: list[Path]):
    for f in files:
        if f.suffix == ".json":
            return json.loads(f.read_text())
    if files:
        return json.loads(files[0].read_text())
    raise FileNotFoundError("no file")
