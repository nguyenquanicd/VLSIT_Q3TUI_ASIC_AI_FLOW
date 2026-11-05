"""The models each provider offers and the efforts each model takes (docs/spec/config.md "Providers").

- Models: the Claude subscription has a fixed list (no API lists the models of a Claude Code login); the Claude API
  and the OpenAI API (or an endpoint that speaks either) are asked (`/v1/models`, `/models`); the OpenAI subscription
  offers what LiteLLM routes there (its `chatgpt/*` models). Asked lists are cached for CACHE_TTL_S in
  `$Q3TUI_HOME/models/`; an endpoint that cannot be asked gives the suggested names and a note, never an error.
- Efforts: Claude Code sends `low | medium | high | xhigh | max` for any model (`output_config.effort`). A Claude model
  takes them all but Haiku 4.5 (none); with `claude_api` any model takes them all (the endpoint maps them: no LiteLLM
  between); through the gateway (`openai`, `openai_api`) LiteLLM turns it into the OpenAI `reasoning_effort`, so a
  model takes low · medium · high and xhigh / max when LiteLLM's model data says it supports them, none when it does
  not reason.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request

from q3tui.core import keys

CLAUDE_MODELS = (
    ("claude-opus-5-5", "Opus 5.5 — best quality"),
    ("claude-sonnet-5-5", "Sonnet 5.5 — fast, cheaper (default)"),
    ("claude-haiku-5-5", "Haiku 5.5 — cheap and fast; thinks at length before it answers"),
    ("claude-haiku-4-5", "Haiku 4.5 — cheapest, for trying the flow (no effort setting)"),
    ("claude-fable-5-1", "Fable 5.1 — most capable, most expensive"),
)
EFFORTS = ("low", "medium", "high", "xhigh", "max")  # what Claude Code sends, lowest first
BASE_EFFORTS = ("low", "medium", "high")
CLAUDE_API_BASE = "https://api.anthropic.com"
OPENAI_API_BASE = "https://api.openai.com/v1"
CACHE_TTL_S = 600
TIMEOUT_S = 8
# names of the OpenAI API's models that are not chat models (images, audio, embeddings, …): left out of the list
_NOT_CHAT = ("embedding", "tts", "whisper", "dall-e", "image", "audio", "transcribe", "moderation", "realtime", "sora",
             "davinci", "babbage", "search", "computer-use", "deep-research", "container")
_litellm_map: dict | None = None


def _hints(provider: str) -> list[tuple[str, str]]:
    from q3tui.llm.provider import MODEL_HINTS

    return [(m, m) for m in MODEL_HINTS.get(provider, ())]


def litellm_map() -> dict:
    """LiteLLM's model data (from the gateway's environment); {} when LiteLLM is not installed yet."""
    global _litellm_map
    if _litellm_map is None:
        from q3tui.llm import gateway

        found = sorted(gateway.venv().glob("lib/python*/site-packages/litellm/model_prices_and_context_window_backup.json"))
        try:
            _litellm_map = json.loads(found[-1].read_text()) if found else {}
        except (OSError, ValueError):
            _litellm_map = {}
    return _litellm_map


def _cache_path(provider: str, base: str | None):
    key = hashlib.sha256(f"{provider}|{base or ''}|{bool(keys.get(_key_name(provider) or ''))}".encode()).hexdigest()[:16]
    return keys.home() / "models" / f"{provider}-{key}.json"


def _key_name(provider: str) -> str | None:
    return {"claude_api": "ANTHROPIC_API_KEY", "openai_api": "OPENAI_API_KEY"}.get(provider)


def _get_json(url: str, headers: dict) -> dict:
    # (a named client: Cloudflare-fronted endpoints refuse Python's default User-Agent, error 1010)
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "q3tui", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode())


def claude_model_urls(base: str | None) -> list[tuple[str, bool]]:
    """Where a Claude-API endpoint may list its models, as (url, OpenAI-style auth): `{base}/v1/models`; for a gateway
    serving the Claude API under `…/anthropic`, also its sibling `…/v1/models` (the gateway's own list)."""
    root = (base or CLAUDE_API_BASE).rstrip("/")
    root = root[: -len("/v1")] if root.endswith("/v1") else root  # (a base given with /v1: not /v1/v1/models)
    urls = [(root + "/v1/models?limit=1000", False)]
    if root.endswith("/anthropic"):
        urls.append((root[: -len("/anthropic")] + "/v1/models", True))
    return urls


def _ask(provider: str, base: str | None) -> list[tuple[str, str]]:
    """The models the endpoint lists (raises on any failure)."""
    if provider == "claude_api":
        key = keys.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        urls = claude_model_urls(base)
        for i, (url, bearer) in enumerate(urls):
            try:
                data = _get_json(url, {"authorization": f"Bearer {key}"} if bearer
                                 else {"x-api-key": key, "anthropic-version": "2023-06-01"})
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 404 or i == len(urls) - 1:
                    raise
        return [(m["id"], m.get("display_name") or m["id"]) for m in data.get("data", []) if m.get("id")]
    key = keys.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    data = _get_json((base or OPENAI_API_BASE).rstrip("/") + "/models", {"authorization": f"Bearer {key}"})
    ids = sorted({m["id"] for m in data.get("data", []) if m.get("id")})
    return [(i, i) for i in ids if not any(x in i.lower() for x in _NOT_CHAT)]


def _chatgpt_models() -> list[tuple[str, str]]:
    data = litellm_map()
    out = []
    for k, v in data.items():
        if k.startswith("chatgpt/") and isinstance(v, dict) and v.get("mode") in ("chat", "responses"):
            out.append(k.split("/", 1)[1])
    return [(m, m) for m in sorted(set(out), key=_model_order)]


def _model_order(name: str):
    """Newest-looking first: gpt-6.1 before gpt-6 before gpt-5.6 …"""
    import re

    nums = [int(x) for x in re.findall(r"\d+", name)[:2]]
    return (-(nums[0] if nums else 0), -(nums[1] if len(nums) > 1 else -1), name)


def list_models(provider: str, base: str | None = None, refresh: bool = False) -> tuple[list[tuple[str, str]], str]:
    """(models as (id, label), a note when the list is not the provider's own) for `provider`."""
    if provider == "claude":
        return list(CLAUDE_MODELS), ""
    if provider == "openai":
        found = _chatgpt_models()
        if found:
            return found, ""
        return _hints(provider), "LiteLLM is not installed yet (q3tui gateway install): suggested models shown"
    path = _cache_path(provider, base)
    if not refresh and path.is_file() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
        try:
            return [tuple(x) for x in json.loads(path.read_text())], ""
        except ValueError:
            pass
    try:
        found = _ask(provider, base)
    except Exception as exc:  # (network, HTTP, JSON, a missing key: the suggestions instead)
        fallback = list(CLAUDE_MODELS) if provider == "claude_api" else _hints(provider)
        return fallback, f"could not list the models ({str(exc)[:120]}): suggested models shown"
    if not found:
        return (list(CLAUDE_MODELS) if provider == "claude_api" else _hints(provider)), "the endpoint listed no models"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found))
    return found, ""


def _model_info(provider: str, model: str) -> dict | None:
    data = litellm_map()
    for k in ((f"chatgpt/{model}",) if provider == "openai" else ()) + (model, f"openai/{model}"):
        if isinstance(data.get(k), dict):
            return data[k]
    return None


def efforts_for(provider: str, model: str | None) -> tuple[tuple[str, ...], str]:
    """(the effort levels `model` takes, lowest first; a note when they are a guess)."""
    model = model or ""
    if model.startswith("claude-"):
        return (() if model.startswith("claude-haiku-4") else EFFORTS), ""
    if provider == "claude_api":  # (no LiteLLM between: Claude Code sends output_config.effort as is, the endpoint maps it)
        return EFFORTS, ""
    info = _model_info(provider, model)
    if info is None:
        return BASE_EFFORTS, f"{model}: not in LiteLLM's model data — the usual levels"
    if not info.get("supports_reasoning"):
        return (), ""
    levels = list(BASE_EFFORTS)
    if info.get("supports_xhigh_reasoning_effort"):
        levels.append("xhigh")
    if info.get("supports_max_reasoning_effort"):
        levels.append("max")
    if isinstance(info.get("reasoning_effort_levels"), list):
        levels = [e for e in levels if e in info["reasoning_effort_levels"]] or levels
    return tuple(levels), ""


def fit_effort(effort: str | None, levels: tuple[str, ...]) -> str | None:
    """`effort` if the model takes it, else its highest level below it (or its lowest); None when it takes none."""
    if not levels:
        return None
    if effort is None or effort in levels:
        return effort
    if effort not in EFFORTS:
        return levels[-1]
    below = [e for e in levels if EFFORTS.index(e) <= EFFORTS.index(effort)]
    return below[-1] if below else levels[0]
