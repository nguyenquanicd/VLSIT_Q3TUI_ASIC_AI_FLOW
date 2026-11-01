"""The keys of config.yaml, their types, ranges and defaults (spec/config.md)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Effort = Literal["low", "medium", "high", "xhigh", "max"]
GateMode = Literal["manual", "auto", "unattended"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLM(_Strict):
    model: str = "claude-sonnet-5-5"
    fallback_model: str | None = None
    effort: Effort | None = "medium"
    thinking_budget: int | None = Field(6000, ge=0)
    timeout_s: int | None = Field(None, ge=1)
    task_max_cost: float | None = Field(None, gt=0)
    tool_output_limit: int = Field(6000, ge=500)
    task_token_budget: int | None = Field(1_000_000, ge=10_000)
    env: dict[str, str] = Field(default_factory=dict)


class Pipeline(_Strict):
    flow: str = "vlsit"
    gate_mode: GateMode | None = None
    auto_confirm_reviews: bool = False
    max_fix_rounds: int = Field(5, ge=1, le=20)
    max_parallel_stage: int = Field(1, ge=1)
    max_cost: float | None = Field(None, gt=0)


class StepSettings(_Strict):
    gate: GateMode | None = None
    model: str | None = None
    effort: Effort | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class StageSettings(_Strict):
    params: dict[str, Any] = Field(default_factory=dict)


class ToolRole(_Strict):
    cmd: str
    parse: str | dict[str, list[str]] = "generic"
    description: str = ""
    cwd: str | None = None
    timeout_s: int | None = Field(None, ge=1)
    env: dict[str, str] = Field(default_factory=dict)
    modules: list[str] = Field(default_factory=list)
    ok_returncodes: list[int] = Field(default_factory=lambda: [0])
    supports: list[str] = Field(default_factory=list)


class Tools(_Strict):
    timeout_s: int = Field(600, ge=1)
    modules: list[str] = Field(default_factory=list)
    modules_init: str | None = None
    setup_script: str | None = None
    roles: dict[str, ToolRole] = Field(default_factory=dict)


class Pdk(_Strict):
    title: str
    node_nm: int = Field(ge=1)
    foundry: str = ""
    globs: list[str]
    include: str | None = None
    default_corner: str | None = None
    probe_ns: float = Field(1.0, gt=0)


class Fpga(_Strict):
    title: str = ""


class McpServer(_Strict):
    type: Literal["http", "sse", "stdio"]
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class Tui(_Strict):
    theme: Literal["vlsit-dark"] = "vlsit-dark"
    icons: Literal["nerd", "unicode"] = "nerd"


class Config(_Strict):
    llm: LLM = Field(default_factory=LLM)
    pipeline: Pipeline = Field(default_factory=Pipeline)
    steps: dict[str, StepSettings] = Field(default_factory=dict)
    stages: dict[str, StageSettings] = Field(default_factory=dict)
    tools: Tools = Field(default_factory=Tools)
    pdks: dict[str, Pdk] = Field(default_factory=dict)
    fpgas: dict[str, Fpga] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict)
    tui: Tui = Field(default_factory=Tui)


# The keys written into a new user config at installation (spec/config.md "Defaults and installation").
INSTALLED_KEYS = ("llm.model", "llm.effort", "pipeline.flow")
