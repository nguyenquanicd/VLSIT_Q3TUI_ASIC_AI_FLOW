# Q3TUI Configuration — `q3tui.yaml`

## Resolution order (layers merge; later wins)

1. Built-in defaults
2. `$Q3TUI_HOME/q3tui.yaml` (default `~/.q3tui`) — site settings: tool modules, default model
3. `<project>/q3tui.yaml` — per-design overrides
4. `q3tui --config <path>` or `$Q3TUI_CONFIG`
5. Command-line flags: `q3tui --model <id> [--effort <level>] ...`

In the TUI, `,` (or `/settings [tab]`) opens the **settings dialog**: tabs General, Gates, LLM,
Spec, RTL and Models per step, built from `q3tui/core/settings.py`.
Changes are validated against this schema, apply from the next stage on, and are written
to `<project>/q3tui.yaml` unless "Only for this session" is ticked. The assistant
has the same (`get_settings` / `set_settings`).

Layers are deep-merged, so a project file that only sets `llm.model` keeps the user
file's tool modules. Unknown keys are rejected, except the settings of the removed `units` /
`steps` flows (`req`, `arch`, `model`, `sim`, `triage`, `units`, …), which older config files
still carry: they are dropped on load (`config._legacy`). Strings expand `~` and `$ENV`.
`q3tui config show` prints the merged config and which layers it came from.

## Schema

```yaml
llm:
  provider: claude                # where the requests go ("Providers" below): claude | claude_api | openai | openai_api
  api_base: null                  # claude_api / openai_api: the endpoint (null = the official API)
  model: claude-sonnet-5-5          # any model id the provider knows (gpt-5.3-codex, … for the OpenAI providers)
  fallback_model: null
  effort: high                    # low | medium | high | xhigh | max | null (Haiku 4.5, other providers' models). Like Claude Code: thinking
                                  # is never cut short and the effort never lowered (runaway_thinking_tokens /
                                  # runaway_seconds are ignored); no turn or time limit either
  thinking_budget: 6000           # only when effort is null: cap extended thinking (0 = off, null = model default)
  max_turns: (ignored)            # like Claude Code: no turn limit, Claude decides when a task is done
  max_budget_usd: null            # per LLM stage
  tool_output_limit: 6000         # characters one tool call may return (head + tail kept): results are re-sent every turn
  stage_token_budget: 1000000     # warn when one stage reads more input tokens (cache included); null = never
  steps:                          # per-step model / effort (Settings → "Models per step"); unset = the values above,
                                  # except spec: effort medium by default (`spec: {effort: default}` = the global one)
    rtl:    {model: claude-sonnet-5-5, effort: high}
    parse:  {model: claude-haiku-4-5}               # effort: default | none | low … max ("none" for Haiku)
    # keys: spec parse config rtl assistant (any other flow's step ids are accepted too)
  timeout_s: null                 # per LLM stage: null = no limit (like Claude Code); a number only if you want one
  env: {}                         # passed to the SDK, after the provider's (a value here wins), e.g. ANTHROPIC_BASE_URL. Q3TUI sets ENABLE_CLAUDEAI_MCP_SERVERS=false by default (the account's
                                  # claude.ai connectors added 100–200k tokens to every stage that used a tool); "true" here turns them back on

project:                          # folder names inside the project (docs/spec/project-layout.md); all relative to its root
  spec_dir: spec                  # your spec documents, intent.md, template.yaml, spec.md, ref/
  config_dir: config              # tools.json, pdks.json, rtl_rules.md, skills/, sanity/<role>_knowledge.md
  constraints_dir: constraints    # constraints/sdc/ (sdc.json and the rendered Tcl files)
  schemas_dir: schemas            # generated JSON artifacts (structured_spec.json, final_config.json, …), questions/<step>.*
  reviews_dir: reviews            # yours, kept on reset: parse / config reviews, sanity answers
  reports_dir: reports            # readable results rendered by code
  docs_dir: docs                  # the final specification only
  src_dir: src                    # src/rtl (the rtl flow) and src/tb (the dv flow)
  rtl_dir: src/rtl                # where the rtl flow writes (its csr/, style_lint/, smoke/ are inside)
  tb_dir: src/tb                  # the dv flow's testbench; denied to the RTL stages (independence)
  fpga_src_dir: src/fpga          # the FPGA flow's own sources: the memory initialization files fpga_port makes
  build_dir: build                # disposable tool output; gitignored by `q3tui init`
  syn_dir: build/syn              #   build/syn/fpga, build/syn/asic
  sim_dir: build/sim              #   lint / synthesis / simulation logs
  state_dir: .q3tui
  req_dir: req                    # req, arch, model: team-mode role folders (NOTES.md) and independence deny lists
  arch_dir: arch
  model_dir: model

pipeline:
  flow: spec                      # the flow: a name (built-in `spec` / `rtl` / `example`, or a file / folder in <project>/flows/ or
                                  # ~/.q3tui/flows/) or a path to a flow file (docs/spec/flows.md; `--flow`, `q3tui flow list|check`)
  gates: []                       # steps with a review gate (step ids of the flow). Empty: the flow file's own `gate:`s;
                                  # set: replaces them. `--yes` approves all (even blocking questions)
  session: null                   # null = the flow's (`session:` in the flow file); flow = one persistent session for the whole flow; fresh = a session per stage
  gate_modes: {}                  # per-step gate mode: human | auto | auto_answer | none — overrides the flow file's (TUI: g, /gate,
                                  # Settings → Gates; CLI: `q3tui gate STEP MODE`; assistant: set_gate_mode)
  auto_approve: false             # gates approve themselves, but stop for blocking questions (/autoapprove, --auto-approve)
  auto_answer: false              # unattended: gates approve, every question takes its default, proposals accepted (/autoanswer, --auto-answer)
  auto_confirm_reviews: false     # confirm a step's own reviewable items (flagged REQs, changed parameters) without asking (/autoconfirm)
  history: true                   # the project's versions in .q3tui/history/: one per finished step and per flow that passed (docs/spec/history.md)
  design_flows: [rtl]             # the flows whose steps make the design (rtl includes spec → parse → config): a run changes the design only
                                  # while no run of another flow is in a step (pipeline.md "Runs of several flows"; an old `lanes:` block is read for it)
  chain: [spec, rtl, dv, sanity, fpga]  # the full unattended run (`q3tui auto`, /auto): these flows in order, until each passed with the final RTL
  chain_max_runs: 3               # most runs of one flow in it (a flow that changed the RTL makes dv / sanity / fpga run again; pipeline.md)
  max_fix_iterations: 5           # fix rounds (a step's triage → fixes → check loop) when the step sets no `max_fix_rounds`
  escalate_after_repeats: 2       # same finding, no progress → ask human
  step_options: {}                # per-step options on top of the flow file's: {rtl: {lint_max_warnings: 0}}
  step_flow: {}                   # per-step view / pass / notes overrides (/step; docs/spec/flows.md)

spec:
  self_review: true               # review pass after a full draft; returns only its changes (/specreview)

tui:
  icons: unicode                  # unicode (✔ ⚑ ◐ …) | nerd (a "… Nerd Font Mono" font) | ascii (any font)
  language: en                    # en | vi | ko

tb:                               # the dv flow's tb step (docs/spec/dv-flow.md)
  max_fix_attempts: 3             # extra rounds when the plan / TB checks still fail
  max_turns: 30                   # agent turns per TB stage
  tests_per_agent: 6              # test cases per agent (agents run in parallel)
  parallel: 4                     # test-case agents at once

rtl:                              # the rtl flow's rtl step
  max_fix_attempts: 3             # extra rounds when Q3TUI's own checks (rules, lint, synthesis) still fail
  parallel: 4                     # modules written at once
  max_turns: (ignored)            # like Claude Code: no turn limit, Claude decides when a task is done

team:                             # role sessions (team.md)
  enabled: false                  # every role's tasks go to that role's one persistent session (`q3tui team`)
  dedupe_chars: 300               # sections (then paragraphs) at least this long are sent once per session (0: never)
  unit_sessions: own              # own: a module's RTL / a TB group gets its own small session (resumed for its fixes); role: the role's one session
  fork: true                      # parallel tasks of a role fork its session at its last idle point (else they queue)
  max_context: null               # null: Claude compacts a role session itself when it fills up (like Claude Code);
                                  # a token count compacts it after the task that passed it

tools:
  file: null                      # tools file (tools.json / tools.yaml); default: <project>/config/tools.json|yaml
  roles: {}                       # tools by role for the flows (overrides the file's): {lint: {cmd: "vcs -full64 -sverilog +lint=all -f {filelist} …",
                                  #   parse: vcs, supports: [], description: …}, synth: {…}, sim: {…}, run: {…}}; docs/spec/flows.md "Tools"
  timeout_s: 600                  # per tool invocation
  setup_script: null              # sourced before tools
  modules: []                     # `module load`ed before every tool
  modules_init: null              # default $MODULESHOME/init/bash
  syntax:    {adapter: slang}
  simulator: {adapter: vcs, bin: vcs, extra_args: [], modules: []}
  lint:      {adapter: spyglass, bin: sg_shell, rules_file: null, modules: []}
  debug:     {adapter: verdi, bin: verdi, modules: []}

mcp_servers: []                   # extra MCP servers available to LLM stages
```

Tools run as `bash -c 'source <setup_script> && source <modules_init> && module load <tools.modules + role modules> && exec <cmd>'`.
An example config is in [`q3tui.example.yaml`](../../q3tui.example.yaml).

## Providers

Every LLM stage runs on the Claude Agent SDK; `llm.provider` decides where its requests go (`q3tui/llm/provider.py`):

| `llm.provider` | Requests go to | Needs |
|---|---|---|
| `claude` (default) | Anthropic, with the Claude Code login (the Claude subscription) | a Claude Code login |
| `claude_api` | the Claude API, or any endpoint that speaks it (`llm.api_base`) | `ANTHROPIC_API_KEY` |
| `openai` | OpenAI with a ChatGPT login (the subscription; the Codex models), through the gateway | `q3tui gateway login` |
| `openai_api` | the OpenAI API, or any endpoint that speaks it (`llm.api_base`: vLLM, Ollama, a company endpoint), through the gateway | `OPENAI_API_KEY` |

- **The gateway** (`q3tui/llm/gateway.py`): a LiteLLM proxy on 127.0.0.1 that takes the SDK's Anthropic-format requests and
  forwards them to the OpenAI provider; every model name goes to the provider as it is. Q3TUI starts it when a stage needs
  it and keeps it running between runs (`q3tui gateway status | start | stop`); another project's provider settings
  restart it with that config. It runs LiteLLM from its own virtual environment, `~/.q3tui/gateway/venv` (LiteLLM's
  proxy pins an older `rich` than Textual), made once with uv by `q3tui gateway install` (run by `install.sh`, or by
  the first start or login that needs it) and used directly afterwards. Its files: `~/.q3tui/gateway/` (`venv/`,
  `config.yaml`, `state.json`, `token` — the proxy's key, mode 600, `chatgpt/` — the ChatGPT login, `gateway.log`).
- **Keys** (`q3tui/core/keys.py`): `~/.q3tui/keys.env` (mode 600), set with `q3tui keys set NAME` or the settings
  dialog's Provider tab; an environment variable of the same name wins. Never in `q3tui.yaml`: the dialog and `ops`
  write them only to that file and never read a value back.
- **Models of other providers** take no `effort` and no `thinking_budget` (they think as their provider decides); the
  SDK's small background calls go to the same model (`ANTHROPIC_DEFAULT_*_MODEL`). Switching the provider in the
  settings switches a model the new provider does not have (to `gpt-5.5`, or back to the default Claude model).
- **Cost**: Claude Code prices only the models it knows: for another provider's model a stage may report $0.
- A provider that cannot serve (no key, no login, the gateway did not start) fails the stage with what is missing.
