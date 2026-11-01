"""Sites: what is downloaded from outside, kept in a `sites/` folder, recorded in `sites.yaml` next to it, and
linked into Q3TUI's folders (spec/workspace.md "Sites", spec/flow.md "Where the files come from").

The same form at both levels: `$Q3TUI_HOME/{sites.yaml,sites/}` (flow repositories, packages of steps) and
`<project>/.q3tui/{sites.yaml,sites/}` (the project's vendor sources).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FOLDER_KINDS = ("flows", "stages", "steps", "skills")  # one link per folder
FILE_KINDS = ("templates", "rules", "knowledge")  # one link per file


class SiteError(Exception):
    pass


@dataclass
class Site:
    name: str
    git: str
    ref: str
    links: list[str] = field(default_factory=list)


class Sites:
    """The `sites.yaml` and `sites/` of one level (`base` is `$Q3TUI_HOME` or `<project>/.q3tui`)."""

    def __init__(self, base: Path):
        self.base = base
        self.file = base / "sites.yaml"
        self.dir = base / "sites"

    def read(self) -> dict[str, Site]:
        if not self.file.is_file():
            return {}
        data = yaml.safe_load(self.file.read_text()) or {}
        out = {}
        for name, entry in data.items():
            source = (entry or {}).get("source") or {}
            out[name] = Site(name, str(source.get("git", "")), str(source.get("ref", "")), list(entry.get("links") or []))
        return out

    def write(self, sites: dict[str, Site]) -> None:
        data = {s.name: {"source": {"git": s.git, "ref": s.ref}, "links": s.links} for s in sites.values()}
        self.base.mkdir(parents=True, exist_ok=True)
        self.file.write_text(yaml.safe_dump(data, sort_keys=False))

    def fetched(self, name: str) -> bool:
        return (self.dir / name / ".git").exists() or (self.dir / name).is_dir()

    def missing(self) -> list[Site]:
        """Sites recorded but not downloaded ("site not fetched")."""
        return [s for s in self.read().values() if not self.fetched(s.name)]

    # -- installing ---------------------------------------------------------------------------

    def install(self, name: str, git: str, ref: str, *, as_package: bool = False) -> Site:
        """Download `git` at `ref` (a tag or a commit) into `sites/<name>/`, then link its items. Only called when
        you asked for it (the caller shows the source first)."""
        dest = self.dir / name
        if dest.exists():
            raise SiteError(f"site {name} is already downloaded ({dest})")
        self.dir.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--quiet", git, str(dest)])
        _git(["-C", str(dest), "checkout", "--quiet", ref])
        site = Site(name, git, ref)
        site.links = self.link_package(name) if as_package else self.link_items(name)
        sites = self.read()
        sites[name] = site
        self.write(sites)
        return site

    def update(self, name: str, ref: str) -> Site:
        sites = self.read()
        if name not in sites:
            raise SiteError(f"no site {name}")
        dest = self.dir / name
        _git(["-C", str(dest), "fetch", "--quiet", "--tags", "origin"])
        _git(["-C", str(dest), "checkout", "--quiet", ref])
        sites[name].ref = ref
        self.write(sites)
        return sites[name]

    def installed_ref(self, name: str) -> str | None:
        site = self.read().get(name)
        return site.ref if site else None

    # -- linking ------------------------------------------------------------------------------

    def link_items(self, name: str) -> list[str]:
        """One link per flow, stage, step and skill folder, and per file of templates/, rules/, knowledge/.
        An item another site already provides is an error."""
        src_root = self.dir / name
        plan: list[tuple[Path, Path]] = []
        for kind in FOLDER_KINDS:
            for item in sorted((src_root / kind).glob("*")) if (src_root / kind).is_dir() else []:
                if item.is_dir():
                    plan.append((item, self.base / kind / item.name))
        for kind in FILE_KINDS:
            base = src_root / kind
            for item in sorted(base.rglob("*")) if base.is_dir() else []:
                if item.is_file():
                    plan.append((item, self.base / kind / item.relative_to(base)))
        clashes = [str(dst.relative_to(self.base)) for _, dst in plan if dst.exists() or dst.is_symlink()]
        if clashes:
            raise SiteError(f"site {name}: these items already exist: {', '.join(clashes[:10])}")
        links = []
        for src, dst in plan:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src.resolve())
            links.append(str(dst.relative_to(self.base)))
        return links

    def link_package(self, name: str) -> list[str]:
        dst = self.base / "packages" / name
        if dst.exists() or dst.is_symlink():
            raise SiteError(f"package {name} already exists ({dst})")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to((self.dir / name).resolve())
        return [str(dst.relative_to(self.base))]


def _git(args: list[str]) -> None:
    res = subprocess.run(["git", *args], check=False, capture_output=True, text=True)
    if res.returncode != 0:
        raise SiteError(f"git {' '.join(args)}: {res.stderr.strip() or res.stdout.strip()}")
