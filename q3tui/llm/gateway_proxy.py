"""The LiteLLM proxy as the gateway runs it (llm/gateway.py), with Q3TUI's fixes to LiteLLM's requests.

Run by the gateway's own Python (`python -I gateway_proxy.py --config … --port …`), not imported by Q3TUI: it needs only
LiteLLM. Fixes:

- ChatGPT (`chatgpt/*`): the backend refuses input messages of role `system` ("System messages are not allowed").
  LiteLLM turns Claude Code's top-level system prompt into `instructions`, but passes the system messages Claude Code
  adds within a conversation on as `system` input items; they are sent as `developer` messages instead (the role Codex
  itself uses for such instructions).
"""

from __future__ import annotations


def developer_roles(request: dict) -> dict:
    """The request with each `system` input message sent as a `developer` one."""
    items = request.get("input")
    if isinstance(items, list):
        request["input"] = [{**item, "role": "developer"}
                            if isinstance(item, dict) and item.get("role") == "system" else item for item in items]
    return request


def patch() -> None:
    from litellm.llms.chatgpt.responses.transformation import ChatGPTResponsesAPIConfig

    original = ChatGPTResponsesAPIConfig.transform_responses_api_request
    if getattr(original, "_q3tui", False):
        return

    def transform_responses_api_request(self, *args, **kwargs):
        return developer_roles(original(self, *args, **kwargs))

    transform_responses_api_request._q3tui = True
    ChatGPTResponsesAPIConfig.transform_responses_api_request = transform_responses_api_request


if __name__ == "__main__":
    patch()
    from litellm.proxy.proxy_cli import run_server

    run_server()
