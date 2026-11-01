"""The keys of config.yaml, their types, ranges and defaults (spec/config.md)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Effort = Literal["low", "medium", "high", "xhigh", "max"]
GateMode = Literal["manual", "auto", "unattended"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLM(_Strict):
    model: str = Field("claude-sonnet-5-5", description="The model of every LLM task.")
    fallback_model: str | None = Field(None, description="The model used when the main one fails.")
    effort: Effort | None = Field("medium", description="The effort of every LLM task; empty for a model without effort.")
    thinking_budget: int | None = Field(6000, ge=0, description="The thinking tokens of a model without effort; 0 = no thinking.")
    timeout_s: int | None = Field(None, ge=1, description="The longest one LLM task may take, in seconds; empty = no limit.")
    task_max_cost: float | None = Field(None, gt=0, description="The most one LLM task may spend, in USD; empty = no limit.")
    tool_output_limit: int = Field(6000, ge=500, description="The most characters one tool call returns to the LLM.")
    task_token_budget: int | None = Field(1_000_000, ge=10_000, description="Warn when one task reads more input tokens than this.")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables given to the LLM.")


class Pipeline(_Strict):
    flow: str = Field("vlsit", description="The flow a run uses.")
    gate_mode: GateMode | None = Field(None, description="The gate mode of every step; empty = the flow files decide.")
    auto_confirm_reviews: bool = Field(False, description="Confirm every review item.")
    max_fix_rounds: int = Field(5, ge=1, le=20, description="The most rounds of a fix loop (1-20).")
    max_parallel_stage: int = Field(1, ge=1, description="The most stages that run at the same time.")
    max_cost: float | None = Field(None, gt=0, description="The most one run may spend, in USD; empty = no limit.")


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
    timeout_s: int = Field(600, ge=1, description="The longest one tool run may take, in seconds.")
    modules: list[str] = Field(default_factory=list, description="Modules loaded once when Q3TUI loads, for every tool.")
    modules_init: str | None = Field(None, description="The module init script; empty = $MODULESHOME/init/bash.")
    setup_script: str | None = Field(None, description="A script sourced once when Q3TUI loads, for every tool.")
    roles: dict[str, ToolRole] = Field(default_factory=dict, description="How each tool role runs: its command, log reader, and more.")


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
    theme: Literal["vlsit-dark"] = Field("vlsit-dark", description="The theme of the TUI.")
    icons: Literal["nerd", "unicode"] = Field("nerd", description="Nerd Font glyphs, or plain Unicode for any font.")


class Config(_Strict):
    llm: LLM = Field(default_factory=LLM)
    pipeline: Pipeline = Field(default_factory=Pipeline)
    steps: dict[str, StepSettings] = Field(default_factory=dict)
    stages: dict[str, StageSettings] = Field(default_factory=dict)
    tools: Tools = Field(default_factory=Tools)
    pdks: dict[str, Pdk] = Field(default_factory=dict, description="The standard-cell libraries of the ASIC flow.")
    fpgas: dict[str, Fpga] = Field(default_factory=dict, description="The FPGA parts you add.")
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict, description="Outside MCP servers given to the LLM of every step.")
    tui: Tui = Field(default_factory=Tui)


# The keys written into a new user config at installation (spec/config.md "Defaults and installation").
INSTALLED_KEYS = ("llm.model", "llm.effort", "pipeline.flow")
