"""spec/workspace.md: the project, sites, approvals."""

import subprocess
from pathlib import Path

import pytest

from q3tui.workspace import Approvals, Project, SiteError, Sites


def test_find_goes_up_and_open_creates_in_cwd(tmp_path):
    (tmp_path / "p" / ".q3tui").mkdir(parents=True)
    deep = tmp_path / "p" / "src" / "rtl"
    deep.mkdir(parents=True)
    assert Project.find(deep).root == (tmp_path / "p").resolve()
    fresh = tmp_path / "new"
    fresh.mkdir()
    project = Project.open(fresh)
    assert project.root == fresh.resolve() and project.q3.is_dir()
    assert not project.has_run
    ignored = (fresh / ".gitignore").read_text().splitlines()
    assert {".q3tui/state/", ".q3tui/sites/", ".q3tui/packages/"} <= set(ignored)


def test_gitignore_keeps_your_lines(tmp_path):
    (tmp_path / ".gitignore").write_text("build/\n.q3tui/state/\n")
    Project.open(tmp_path)
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines[0] == "build/" and lines.count(".q3tui/state/") == 1


def _repo(path: Path, files: dict[str, str]) -> str:
    path.mkdir(parents=True)
    for rel, text in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)
    run("init", "-q")
    run("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    run("tag", "v1")
    return str(path)


def test_install_links_items_and_records(tmp_path):
    git = _repo(tmp_path / "src", {"flows/vlsit/FLOW.md": "x", "steps/spec/STEP.md": "x",
                                   "templates/spec/vlsit.yaml": "x", "rules/rtl_rules.md": "x"})
    home = tmp_path / "home"
    sites = Sites(home)
    site = sites.install("flows", git, "v1")
    assert (home / "flows" / "vlsit").is_symlink() and (home / "steps" / "spec" / "STEP.md").is_file()
    assert (home / "templates" / "spec" / "vlsit.yaml").is_symlink()
    assert "rules/rtl_rules.md" in site.links
    assert sites.read()["flows"].ref == "v1" and not sites.missing()


def test_two_sites_with_the_same_item_clash(tmp_path):
    a = _repo(tmp_path / "a", {"steps/spec/STEP.md": "x"})
    b = _repo(tmp_path / "b", {"steps/spec/STEP.md": "y"})
    sites = Sites(tmp_path / "home")
    sites.install("a", a, "v1")
    with pytest.raises(SiteError):
        sites.install("b", b, "v1")


def test_package_and_missing_site(tmp_path):
    git = _repo(tmp_path / "pkg", {"CSR_Generation.py": "x"})
    sites = Sites(tmp_path / "home")
    sites.install("apb-csr-generator", git, "v1", as_package=True)
    assert (tmp_path / "home" / "packages" / "apb-csr-generator" / "CSR_Generation.py").is_file()
    assert sites.installed_ref("apb-csr-generator") == "v1"
    proj = Sites(tmp_path / "proj" / ".q3tui")
    (tmp_path / "proj" / ".q3tui").mkdir(parents=True)
    (tmp_path / "proj" / ".q3tui" / "sites.yaml").write_text("ip:\n  source: {git: x, ref: v1}\n  links: []\n")
    assert [s.name for s in proj.missing()] == ["ip"]


def test_approvals_per_project_and_per_content(tmp_path):
    approvals = Approvals(tmp_path / "approvals.yaml")
    p1, p2 = tmp_path / "p1", tmp_path / "p2"
    assert not approvals.allowed(p1, "command", "make lint")
    approvals.allow(p1, "command", "make lint")
    assert approvals.allowed(p1, "command", "make lint")
    assert not approvals.allowed(p1, "command", "make lint2")  # a changed command is asked again
    assert not approvals.allowed(p2, "command", "make lint")  # another project is asked again
