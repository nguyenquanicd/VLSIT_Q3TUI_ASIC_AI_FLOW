"""A stand-in for `codex exec --json` (tests/test_codex_backend.py): records its command line and prompt, talks to the Q3TUI
tool endpoint it was given like Codex does (MCP over HTTP), then prints JSONL events like `codex exec --json`.

FAKE_CODEX_PLAN (JSON): {"calls": [[tool, {args}], …], "reply": "<final message>", "fail": "<turn.failed message>"}
FAKE_CODEX_LOG: where to write {"argv": [...], "prompt": "...", "tool_results": [...]}
"""

import json
import os
import re
import sys
import urllib.request

argv = sys.argv[1:]
prompt = sys.stdin.read()
plan = json.loads(os.environ.get("FAKE_CODEX_PLAN", "{}"))
overrides = {m.group(1): json.loads(m.group(2)) for a in argv if (m := re.match(r"^([\w.]+)=(.*)$", a))}
url = overrides.get("mcp_servers.q3tui.url")
token = os.environ.get(overrides.get("mcp_servers.q3tui.bearer_token_env_var", ""), "")
results = []


def rpc(method, params=None, rid=1):
    req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req).read())


def emit(**event):
    print(json.dumps(event), flush=True)


resume = "resume" in argv
emit(type="thread.started", thread_id=argv[argv.index("resume") + 1] if resume else "thread-1")
emit(type="turn.started")
if url and plan.get("calls"):
    rpc("initialize", {"protocolVersion": "2025-06-18"})
    results.append(rpc("tools/list", rid=2))
    for i, (tool, args) in enumerate(plan["calls"], 3):
        emit(type="item.started", item={"id": f"i{i}", "type": "mcp_tool_call", "server": "q3tui", "tool": tool, "arguments": args})
        out = rpc("tools/call", {"name": tool, "arguments": args}, i)
        results.append(out)
        emit(type="item.completed", item={"id": f"i{i}", "type": "mcp_tool_call", "server": "q3tui", "tool": tool, "status": "completed"})
if os.environ.get("FAKE_CODEX_LOG"):
    with open(os.environ["FAKE_CODEX_LOG"], "a") as f:
        f.write(json.dumps({"argv": argv, "prompt": prompt, "tool_results": results}) + "\n")
if plan.get("fail"):
    emit(type="turn.failed", error={"message": plan["fail"]})
    sys.exit(1)
emit(type="item.completed", item={"id": "m", "type": "agent_message", "text": plan.get("reply", "done")})
emit(type="turn.completed", usage={"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 200, "reasoning_output_tokens": 50})
