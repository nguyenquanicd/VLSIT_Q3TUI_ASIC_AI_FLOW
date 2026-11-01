"""spec/config.md: layers, merge rules, validation, where Q3TUI writes, installation."""

from pathlib import Path

import pytest

from q3tui.config import (
    ConfigError,
    ConfigLayers,
    install_user_config,
    merge,
    parse_session_options,
    set_value,
    unset_value,
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def files(tmp_path):
    return tmp_path / "home" / "config.yaml", tmp_path / "proj" / ".q3tui" / "config.yaml"


def test_defaults_without_files(files):
    cfg = ConfigLayers(*files).config
    assert cfg.llm.model == "claude-sonnet-5-5"
    assert cfg.llm.effort == "medium"
    assert cfg.pipeline.flow == "vlsit"
    assert cfg.pipeline.max_fix_rounds == 5
    assert cfg.pipeline.max_parallel_stage == 1
    assert cfg.pipeline.max_cost is None
    assert cfg.tui.theme == "vlsit-dark" and cfg.tui.icons == "nerd"


def test_layer_order_session_over_project_over_user(files):
    user, project = files
    write(user, "llm:\n  model: a\n  effort: low\n")
    write(project, "llm:\n  model: b\n")
    layers = ConfigLayers(user, project, parse_session_options(["llm.effort=high"]))
    assert layers.config.llm.model == "b"
    assert layers.config.llm.effort == "high"
    assert layers.source("llm.model") == "project"
    assert layers.source("llm.effort") == "session"
    assert layers.source("pipeline.flow") == "default"


def test_merge_rules():
    low = {"pdks": {"gf180": {"title": "x"}, "freepdk45": {"title": "y"}}, "tools": {"modules": ["a", "b"]}}
    high = {"pdks": {"freepdk45": None}, "tools": {"modules": ["c"]}}
    out = merge(low, high)
    assert out["pdks"] == {"gf180": {"title": "x"}}  # null removes, maps merge
    assert out["tools"]["modules"] == ["c"]  # a list replaces the whole list


def test_null_removes_what_lower_layers_set(files):
    user, project = files
    write(user, "pdks:\n  gf180: {title: G, node_nm: 180, globs: [a]}\n  f45: {title: F, node_nm: 45, globs: [b]}\n")
    write(project, "pdks:\n  f45: null\n")
    assert list(ConfigLayers(user, project).config.pdks) == ["gf180"]


def test_unknown_key_is_a_warning_with_a_hint(files):
    user, project = files
    write(user, "llm:\n  modle: x\n")
    layers = ConfigLayers(user, project)
    assert layers.config.llm.model == "claude-sonnet-5-5"
    [w] = layers.warnings
    assert w.key == "llm.modle" and "model" in w.message and w.line == 2


def test_wrong_value_is_an_error_with_file_and_line(files):
    user, project = files
    write(project, "pipeline:\n  max_fix_rounds: 99\n")
    with pytest.raises(ConfigError) as exc:
        ConfigLayers(user, project)
    assert exc.value.file == project and exc.value.line == 2


def test_not_yaml_is_an_error(files):
    user, project = files
    write(user, "llm: [unclosed\n")
    with pytest.raises(ConfigError):
        ConfigLayers(user, project)


def test_wrong_value_in_session_is_an_error(files):
    with pytest.raises(ConfigError):
        ConfigLayers(*files, parse_session_options(["llm.effort=enormous"]))


def test_empty_value_warns(files):
    user, project = files
    write(user, "llm:\n  model:\n")
    layers = ConfigLayers(user, project)
    assert any("empty value" in w.message for w in layers.warnings)


def test_gate_order_before_key(files):
    user, project = files
    write(project, "steps:\n  rtl:\n    gate: manual\n")
    layers = ConfigLayers(user, project, parse_session_options(["pipeline.gate_mode=unattended"]))
    assert layers.gate_mode("rtl") == "unattended"  # the highest layer wins over the more specific key
    layers = ConfigLayers(user, project)
    assert layers.gate_mode("rtl") == "manual"
    assert layers.gate_mode("parse") is None  # the flow files decide


def test_gate_in_one_layer_the_step_wins(files):
    user, project = files
    write(project, "pipeline:\n  gate_mode: auto\nsteps:\n  rtl:\n    gate: manual\n")
    layers = ConfigLayers(user, project)
    assert layers.gate_mode("rtl") == "manual"
    assert layers.gate_mode("spec") == "auto"


def test_session_set_and_unset(files):
    layers = ConfigLayers(*files)
    layers.session_set("llm.model", "claude-opus-5-5")
    assert layers.config.llm.model == "claude-opus-5-5" and layers.source("llm.model") == "session"
    with pytest.raises(ConfigError):
        layers.session_set("llm.effort", "nope")
    assert layers.config.llm.model == "claude-opus-5-5"  # a refused change leaves the session as it was
    layers.session_unset("llm.model")
    assert layers.config.llm.model == "claude-sonnet-5-5"


def test_write_keeps_comments_and_unset_shows_lower_layer(files):
    user, project = files
    write(user, "# mine\nllm:\n  model: a  # my model\n")
    write(project, "llm:\n  model: b\n")
    set_value(user, "pipeline.max_fix_rounds", 7)
    text = user.read_text()
    assert "# mine" in text and "# my model" in text and "max_fix_rounds: 7" in text
    assert unset_value(project, "llm.model")
    assert ConfigLayers(user, project).config.llm.model == "a"
    assert not unset_value(project, "llm.model")


def test_install_writes_three_keys_and_never_overwrites(tmp_path):
    path = tmp_path / "config.yaml"
    assert install_user_config(path)
    layers = ConfigLayers(path, None)
    assert {layers.source(k) for k in ("llm.model", "llm.effort", "pipeline.flow")} == {"user"}
    assert layers.source("llm.timeout_s") == "default"
    path.write_text("llm:\n  model: mine\n")
    assert not install_user_config(path)
    assert path.read_text() == "llm:\n  model: mine\n"


def test_steps_and_stages_sections(files):
    user, project = files
    write(project, "steps:\n  rtl:\n    model: m\n    params: {lang: sv}\nstages:\n  synthesis:\n    params: {target: asic}\n")
    cfg = ConfigLayers(user, project).config
    assert cfg.steps["rtl"].params == {"lang": "sv"}
    assert cfg.stages["synthesis"].params == {"target": "asic"}


def test_tool_role_split_across_layers(files):
    user, project = files
    write(user, "tools:\n  roles:\n    lint: {cmd: 'verible-verilog-lint {filelist}', parse: verible}\n")
    write(project, "tools:\n  roles:\n    lint: {timeout_s: 30}\n")
    role = ConfigLayers(user, project).config.tools.roles["lint"]
    assert role.cmd.startswith("verible") and role.timeout_s == 30
