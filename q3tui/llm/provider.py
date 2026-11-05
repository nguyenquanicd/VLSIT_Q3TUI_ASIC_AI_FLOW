"""Where the LLM stages' requests go: `llm.provider` (docs/spec/config.md "Providers").

Every stage still runs on the Claude Agent SDK (`runtime.build_options`); the provider only sets the environment of
its Claude Code process:

- `claude`      the Claude subscription: the Claude Code login, as before (nothing set).
- `claude_api`  the Claude API, or any endpoint that speaks it (`llm.api_base`): ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY.
- `openai`      an OpenAI (ChatGPT) subscription, the Codex models: through the LiteLLM gateway (`gateway.py`).
- `openai_api`  the OpenAI API, or any endpoint that speaks it (`llm.api_base`): through the gateway.

`llm.env` is applied after these, so a setting there still wins.
"""

from __future__ import annotations

from q3tui.core import keys

PROVIDERS = (
    ("claude", "Claude subscription — your Claude Code login (default)"),
    ("claude_api", "Claude API compatible — the Claude API, or any endpoint that speaks it (API base)"),
    ("openai", "OpenAI subscription — your ChatGPT login: the Codex models (through the gateway)"),
    ("openai_api", "OpenAI API compatible — the OpenAI API, or any endpoint that speaks it (API base; through the gateway)"),
)
PROVIDER_IDS = tuple(p for p, _ in PROVIDERS)

# suggested model names per provider (any name the provider knows works)
MODEL_HINTS = {
    "openai": ("gpt-5.5", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex-max", "gpt-5.1-codex-mini"),
    "openai_api": ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5-codex"),
}


class ProviderError(RuntimeError):
    """The provider cannot be used as configured (a key, the login or the gateway missing)."""


def is_claude_model(model: str | None) -> bool:
    return bool(model) and model.startswith("claude-")


def prepare(cfg) -> None:
    """Start what the provider needs before a stage (the gateway); blocking: run it in a thread."""
    from q3tui.llm import gateway

    provider = cfg.llm.provider
    if gateway.uses_gateway(provider):
        try:
            gateway.ensure(provider, cfg.llm.api_base)
        except gateway.GatewayError as exc:
            raise ProviderError(str(exc)) from None


def stage_env(cfg, model: str) -> dict[str, str]:
    """The environment of one stage's Claude Code process for `model` under `llm.provider`."""
    provider = cfg.llm.provider
    if provider == "claude":
        return {}
    out: dict[str, str] = {}
    if not is_claude_model(model):
        # Claude Code's own small calls (titles, summaries) name Claude models: the same model serves them
        out |= {"ANTHROPIC_DEFAULT_HAIKU_MODEL": model, "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": model, "ANTHROPIC_SMALL_FAST_MODEL": model,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    if provider == "claude_api":
        key = keys.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("llm.provider is claude_api and ANTHROPIC_API_KEY is not set: `q3tui keys set ANTHROPIC_API_KEY`, "
                                "or the Provider tab of the settings (,)")
        out["ANTHROPIC_API_KEY"] = key
        if cfg.llm.api_base:
            out["ANTHROPIC_BASE_URL"] = cfg.llm.api_base
        return out
    from q3tui.llm import gateway

    try:
        url = gateway.ensure(provider, cfg.llm.api_base)
    except gateway.GatewayError as exc:
        raise ProviderError(str(exc)) from None
    tok = gateway.token()
    return out | {"ANTHROPIC_BASE_URL": url, "ANTHROPIC_AUTH_TOKEN": tok, "ANTHROPIC_API_KEY": tok}


def describe(cfg) -> str:
    """One line: the provider and what it still needs."""
    from q3tui.llm import gateway

    provider = cfg.llm.provider
    label = dict(PROVIDERS)[provider].split(" — ")[0]
    base = f" · {cfg.llm.api_base}" if cfg.llm.api_base and provider in ("claude_api", "openai_api") else ""
    need = ""
    if provider == "claude_api" and not keys.is_set("ANTHROPIC_API_KEY"):
        need = " · ANTHROPIC_API_KEY not set"
    elif provider == "openai_api" and not keys.is_set("OPENAI_API_KEY"):
        need = " · OPENAI_API_KEY not set"
    elif provider == "openai" and not gateway.logged_in():
        need = " · no ChatGPT login yet"
    return f"provider: {label}{base} · model {cfg.llm.model}{need}"
