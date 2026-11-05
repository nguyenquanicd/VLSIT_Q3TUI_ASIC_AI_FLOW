"""Q3TUI's own record of a project (docs/spec/history.md): a version of the project's files each time a step finishes (when something
changed) and each time a flow passes; `passed/<flow>` marks the last version a flow passed with.

Kept in .q3tui/history/: a git repository of its own whose files are the project folder, never pushed. Your own git of the project folder,
if any, is not touched (its own folder, its own index, none of your git settings), and it leaves out what the project's .gitignore leaves out,
`build/` and `.q3tui/`. Steps read it by code (the dv triage: what changed in the RTL since a test passed) and give it to the LLM as ground truth."""

from __future__ import annotations

from q3tui.core.compat import lock_file, unlock_file
import functools
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

MAIN = "refs/heads/main"
PASSED = "refs/tags/passed/"


class HistoryError(Exception):
    pass


@dataclass
class Version:
    rev: str
    at: str  # ISO time
    title: str
    body: str = ""
    marks: list[str] = field(default_factory=list)  # passed/<flow>
    files: list[str] = field(default_factory=list)  # what it changed (when asked for)

    @property
    def short(self) -> str:
        return self.rev[:8]

    @property
    def when(self) -> str:
        return self.at[:16].replace("T", " ")


def folder(project) -> Path:
    return project.state_dir / "history"


@functools.cache
def _have_git() -> bool:
    return shutil.which("git") is not None


def enabled(project) -> bool:
    return bool(project.cfg.pipeline.history) and _have_git()


def exists(project) -> bool:
    return (folder(project) / "HEAD").is_file()


def _env(project) -> dict:
    d = str(folder(project))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # (a git hook's environment, yours: not ours)
    env.update(GIT_DIR=d, GIT_WORK_TREE=str(project.root), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, HOME=d, XDG_CONFIG_HOME=d,
               GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="Q3TUI", GIT_AUTHOR_EMAIL="q3tui@localhost", GIT_COMMITTER_NAME="Q3TUI",
               GIT_COMMITTER_EMAIL="q3tui@localhost", LC_ALL="C")
    return env


def _git(project, *args: str, input: str | None = None, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", "-c", "safe.directory=*", *args], cwd=project.root, env=_env(project),
                           input=input, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise HistoryError(f"git could not run: {exc}") from exc
    if check and r.returncode != 0:
        raise HistoryError(f"git {args[0]}: {(r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else f'rc={r.returncode}'}")
    return r.stdout


@contextmanager
def _lock(project) -> Iterator[None]:
    """One writer at a time (runs of several flows finish steps at once)."""
    folder(project).mkdir(parents=True, exist_ok=True)
    with open(folder(project) / "q3tui.lock", "w") as fh:
        lock_file(fh)
        try:
            yield
        finally:
            unlock_file(fh)


def _init(project) -> None:
    if exists(project):
        return
    _git(project, "-c", f"init.defaultBranch={MAIN.rsplit('/', 1)[-1]}", "init", "-q")  # (its core.worktree is overridden: the work tree is given each time)
    (folder(project) / "HEAD").write_text(f"ref: {MAIN}\n")  # (a git older than 2.28 names the branch master)
    (folder(project) / "info").mkdir(exist_ok=True)
    out = [f"/{project.rel(d)}/" for d in (project.build_dir, project.state_dir) if project.rel(d) != str(d)]
    (folder(project) / "info" / "exclude").write_text("# Q3TUI's history leaves these out (and what the project's .gitignore leaves out)\n" + "\n".join(out) + "\n")


def _ref(project, ref: str) -> str | None:
    """A ref's version, from its file when it has one (a git call less on every finished step)."""
    f = folder(project) / ref
    if f.is_file():
        return f.read_text().strip() or None
    return _git(project, "rev-parse", "-q", "--verify", ref, check=False).strip() or None


def _set_ref(project, ref: str, rev: str) -> None:
    """Point a ref at a version by writing its file (whole or not at all; under the lock: a git call less on every finished step)."""
    f = folder(project) / ref
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = folder(project) / "q3tui-ref.tmp"
    tmp.write_text(rev + "\n")
    os.replace(tmp, f)


def head(project) -> str | None:
    if not exists(project):
        return None
    return _ref(project, MAIN)


def _record(project, title: str, body: str, always: bool) -> str:
    _init(project)
    _git(project, "add", "-A", "--ignore-errors", "--", ".", check=False)  # (a file that cannot be read is left out, not the version)
    tree = _git(project, "write-tree").strip()
    parent = head(project)
    seen = folder(project) / "q3tui-tree"  # (the last version and its tree: no git call to compare)
    last_rev, last_tree = (seen.read_text().split() + ["", ""])[:2] if seen.is_file() else ("", "")
    if parent and not always and (last_tree if last_rev == parent else _git(project, "rev-parse", f"{parent}^{{tree}}").strip()) == tree:
        return parent
    rev = _git(project, "commit-tree", tree, *(["-p", parent] if parent else []), input=title.strip() + ("\n\n" + body.strip() if body.strip() else "") + "\n").strip()
    _set_ref(project, MAIN, rev)
    seen.write_text(f"{rev} {tree}\n")
    return rev


def record(project, title: str, body: str = "", mark: str | None = None, always: bool = False) -> str | None:
    """A version of the project as it is now, when it changed since the last one (`always`: also when not, e.g. a flow that passed, unless
    `passed/<mark>` is the last version already); `mark`: `passed/<mark>` points at it. Returns the version (the last one when nothing changed),
    None when the history is off."""
    if not enabled(project):
        return None
    with _lock(project):
        last = head(project)
        again = bool(mark and last and _ref(project, PASSED + mark) == last)
        rev = _record(project, title, body, always and not again)
        if mark:
            _set_ref(project, PASSED + mark, rev)
    return rev


def marks(project) -> dict[str, list[str]]:
    """version → its marks (passed/<flow>)."""
    out: dict[str, list[str]] = {}
    for line in _git(project, "for-each-ref", "--format=%(objectname) %(refname)", PASSED).splitlines():
        rev, _, ref = line.partition(" ")
        out.setdefault(rev, []).append(ref.removeprefix("refs/tags/"))
    return out


def resolve(project, ref: str) -> str:
    """A version from its id (or the start of it), `passed/<flow>`, or HEAD / HEAD~n."""
    if not exists(project):
        raise HistoryError("no history yet: a version is recorded when a step finishes")
    rev = _git(project, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", check=False).strip()
    if not rev:
        raise HistoryError(f"no version '{ref}' (q3tui history: the versions)")
    return rev


def versions(project, limit: int = 50, paths: list[str] | None = None, since: str | None = None, files: bool = False) -> list[Version]:
    """The versions, newest first: the ones that changed `paths`, after `since` (not itself); `files`: with what each one changed."""
    if not exists(project) or head(project) is None:
        return []
    out = _git(project, "log", "--format=%x1e%H%x1f%cI%x1f%s%x1f%b%x1f", *(["--name-only"] if files else []), f"-n{limit}",
               f"{since}..{MAIN}" if since else MAIN, "--", *(paths or []))
    tags = marks(project)
    found = []
    for chunk in out.split("\x1e")[1:]:
        rev, at, title, body, rest = (chunk.split("\x1f") + [""] * 5)[:5]
        found.append(Version(rev, at, title, body.strip(), tags.get(rev, []), [f for f in rest.splitlines() if f.strip()]))
    return found


def changed(project, a: str, b: str = MAIN, paths: list[str] | None = None) -> list[str]:
    """The files that differ between two versions."""
    return [f for f in _git(project, "diff", "--name-only", a, b, "--", *(paths or [])).splitlines() if f.strip()]


def diff(project, a: str, b: str | None = MAIN, paths: list[str] | None = None, max_lines: int | None = None) -> str:
    """The changes from version `a` to `b` (None: a's own changes, against the version before it), as a unified diff; `max_lines` caps it."""
    if b is None:
        a, b = (f"{a}^" if _has_parent(project, a) else _empty_tree(project)), a
    text = _git(project, "diff", "--no-color", a, b, "--", *(paths or []))
    lines = text.splitlines()
    if max_lines and len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n… ({len(lines) - max_lines} more lines)"
    return text.rstrip("\n")


def _has_parent(project, rev: str) -> bool:
    return bool(_git(project, "rev-parse", "-q", "--verify", f"{rev}^", check=False).strip())


def _empty_tree(project) -> str:
    return _git(project, "hash-object", "-t", "tree", os.devnull).strip()


def show(project, ref: str, path: str) -> str:
    """A file as it was in a version."""
    rev = resolve(project, ref)
    try:
        return _git(project, "show", f"{rev}:{path}")
    except HistoryError as exc:
        raise HistoryError(f"{path} is not in version {rev[:8]}") from exc


def restore(project, ref: str, paths: list[str]) -> tuple[str, list[str], list[str]]:
    """Put `paths` (files or folders; [] = everything) back as they were in a version: changed files are written, files made since are deleted;
    a backup of what changes goes to .q3tui/bkp/ and the version before and after are recorded. Returns (version, written, deleted)."""
    rev = resolve(project, ref)
    spec = [p.rstrip("/") for p in paths if p.strip()] or ["."]
    with _lock(project):
        _record(project, f"before restoring {', '.join(spec)} from {rev[:8]}", "", False)
        then = set(_git(project, "ls-tree", "-r", "--name-only", rev, "--", *spec).splitlines())
        now = set(_git(project, "ls-files", "--", *spec).splitlines())
        gone = sorted(now - then)
        write = sorted(then & set(_git(project, "diff", "--name-only", rev, "--", *spec).splitlines()))  # (the recorded index is the project as it is)
        project.backup([project.root / f for f in [*gone, *write]])
        if write:
            _git(project, "checkout", rev, "--pathspec-from-file=-", input="\n".join(write) + "\n")
        for f in gone:
            (project.root / f).unlink(missing_ok=True)
        _record(project, f"restored {', '.join(spec)} from {rev[:8]}", f"restored-from: {rev}", True)
    return rev, write, gone
