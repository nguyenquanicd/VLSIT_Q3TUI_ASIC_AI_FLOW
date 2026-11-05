# Multi-Model Routing and Parallel Task Orchestration

## Purpose

This document proposes how Q3TUI can route different AI models to different workflow steps and run independent work in parallel. It describes the current implementation, the target architecture, the TUI behavior, the provider and worker contracts, and an implementation sequence.

The control plane remains deterministic Q3TUI code. Models may recommend a plan or produce task content. The engine validates plans, starts work, enforces permissions and budgets, validates results, records evidence, and stops at review gates.

## Executive Recommendation

Build this in Q3TUI in four layers:

1. A provider/model registry with explicit capability metadata.
2. A route resolver that selects a profile for each step or task.
3. A bounded worker scheduler for tasks whose inputs and write sets are independent.
4. A result validator and fan-in stage that merges evidence and routes conflicts or missing requirements to a gate.

Keep model selection available through the TUI. Use YAML as the persisted configuration and an advanced override surface; users should not have to edit YAML to select a model.

Start with explicit per-step routing and deterministic fan-out for already-known independent work, such as RTL modules or test groups. Add model-proposed dynamic decomposition only after budgets, task schemas, workspace isolation, cancellation, and audit records exist.

## Current Q3TUI Behavior

### Per-step model selection

The TUI already has a Settings tab named Models per step. It creates model and effort settings for each step in the active flow. Settings are validated, applied from the next stage, and saved to the project's q3tui.yaml when the user chooses to persist them. The TUI is therefore already the user-facing editor; YAML is a persistence format and an advanced manual configuration surface.

This support currently applies to Claude model IDs. The list is hard-coded in q3tui/core/settings.py. The global provider backend is selected by llm.backend and currently has the values claude and codex.

### Important Codex limitation

The Codex backend reads the model from llm.codex.model. Its runner does not apply llm.steps.<step>.model. Therefore, selecting different models per step in the current TUI works with the Claude backend but does not currently route Codex models per step. The UI also shows Claude model IDs, not a provider-filtered catalog for Codex.

The first user-facing improvement should make this behavior explicit: show supported provider/model combinations, disable or hide unsupported settings, and never silently accept a route that the active backend ignores.

### Sessions and parallel work

Q3TUI already has team roles, persistent role sessions, unit-level sessions, and some parallel work controls. Claude sessions can fork from a known idle point for supported parallel tasks. In the current Codex CLI backend, concurrent tasks of the same role queue because that backend does not fork the role thread.

This is useful groundwork, but provider session behavior is not uniform. A provider adapter must advertise whether it supports fresh sessions, resume, fork, streaming, interruption, tool calls, and structured output.

### Source locations

- q3tui/core/settings.py — TUI setting definitions, model choices, and the Models per step tab.
- q3tui/core/config.py — LLM backend configuration and per-stage Claude model resolution.
- q3tui/core/ops.py — validation and application of TUI settings, with optional persistence to q3tui.yaml.
- q3tui/llm/runtime.py — shared stage contract and backend dispatch.
- q3tui/llm/codex/runner.py — Codex CLI model selection and stage invocation.
- q3tui/llm/roles.py — role sessions, unit sessions, and session queue/fork behavior.
- docs/spec/config.md, docs/spec/team.md, docs/spec/codex-backend.md — current user-facing configuration and session behavior.

## Terminology

| Term | Meaning in Q3TUI |
|---|---|
| Provider | A service or local runtime that accepts model requests, such as an API, agent SDK, CLI process, or local inference server. |
| Model | A provider-specific model identifier and version. Model IDs are not portable across providers. |
| Model profile | A named, reusable combination of provider, model, capability constraints, and default generation settings. |
| Step | A declared node in a Q3TUI flow, such as spec, RTL, lint, or verification. |
| Task | A bounded unit of work within a step, such as writing one module or checking one test group. |
| Worker | A running task invocation with a model profile, input contract, permissions, output schema, budgets, and workspace. |
| Session or thread | Provider-owned conversational state that may support resume, fork, or streaming. It is not the canonical project state. |
| Orchestrator | Q3TUI's deterministic engine and scheduler. A model can propose work, but it does not own execution state. |

Do not equate these terms. A model is not a worker, a session is not a task, and a provider session ID is not a workflow checkpoint.

## Target Architecture

    User / TUI
        |
    Q3TUI Engine: flow DAG, durable run state, review gates
        |
        +-- Route resolver: step/task -> model profile
        +-- Worker scheduler: dependencies, concurrency, quotas, cancellation
        +-- Provider adapters: Claude, Codex, future API or local runtimes
        +-- Policy layer: input visibility, writable files, tools, data policy
        +-- Result validator: schema, artifact ownership, evidence, tool status
        |
    Model workers in isolated task contexts
        |
    Fan-in / conflict resolution / deterministic EDA checks
        |
    Human review gate or next flow step

The engine owns the source of truth: task IDs, status, inputs, artifact hashes, approvals, and evidence. Provider transcripts may be resumed as an optimization, but Q3TUI must be able to continue from saved project artifacts if a provider session expires or cannot be transferred.

## Recommendation 1: Add Provider and Model Profiles

### Why

The current configuration has one global backend. A global backend cannot express “use provider A for spec, provider B for RTL, and provider C for an independent review.” A single model ID also cannot describe provider-specific tool support, session semantics, token accounting, or data residency.

### Technical implementation

Add typed configuration objects:

- ProviderConfig: provider name, adapter kind, endpoint or CLI path, authentication reference, timeout, and provider-specific non-secret settings.
- ModelProfile: profile name, provider key, model ID, version or alias policy, supported capabilities, default effort, context limit, and pricing metadata.
- StepRoute: profile or inherit, effort, output budget, allowed tools, timeout, retry policy, and optional fallback profile.

Do not store API keys, OAuth tokens, or passwords in project YAML. Read secrets from environment variables, OS credential storage, or the provider's own login flow. YAML may store a secret reference such as an environment variable name.

Conceptual configuration only; this schema is a proposal and is not implemented:

    llm:
      default_profile: general_reasoning
      profiles:
        general_reasoning:
          provider: provider_a
          model: model_id_a
          effort: high
        rtl_writer:
          provider: provider_b
          model: model_id_b
          effort: high
        independent_review:
          provider: provider_c
          model: model_id_c
      routes:
        spec: general_reasoning
        rtl: rtl_writer
        rtl_review: independent_review

Keep user-facing settings separate from adapter implementation details. A provider adapter should normalize requests, streaming events, tool calls, structured outputs, token usage, cost, errors, cancellation, and session lifecycle into a shared internal contract.

Suggested adapter contract:

- invoke(request) returns an invocation result and normalized events.
- start_session(request), resume_session(session_ref, request), and fork_session(session_ref, checkpoint, request) are optional capabilities, not mandatory methods every provider must emulate.
- interrupt(invocation_ref) stops active work when the provider supports it.
- capabilities(profile) reports supported structured output, tools, streaming, resume/fork, context sizes, and data policy.
- errors normalize to authentication, quota/rate-limit, timeout, context-limit, tool-policy, invalid-output, interrupted, or provider-failure classes.

Use a capability check before execution. If a step requires tools or structured output that a profile does not support, reject the route in the UI or use a declared compatible adapter. Do not quietly remove required tools.

### Acceptance criteria

- Every run record names provider, model ID, model version/alias, adapter version, and route source.
- An unsupported capability is reported before the stage starts.
- Secret values never appear in q3tui.yaml, prompts, or ordinary logs.
- A route can be replayed with the same explicit model/profile and saved inputs.

## Recommendation 2: Make the TUI the Primary Model Selector

### Answer to the user's question

Yes. The current TUI already lets the user select a model for each step in Settings → Models per step when using the Claude backend. Changes take effect from the next stage. The user can persist those choices to q3tui.yaml or keep them for the current session.

The current limitation is provider coverage: the picker contains Claude model IDs, while the Codex backend uses one global Codex model and ignores the per-step model field. The next version should make provider and model selection work consistently for all supported backends.

### Proposed TUI experience

Use a Models per step screen with one row per step:

| Step | Provider | Model profile | Effort | Budget |
|---|---|---|---|---|
| Spec | Provider A | General reasoning | High | Per-stage |
| RTL | Provider B | RTL writer | High | Per-stage |
| RTL review | Provider C | Independent review | Medium | Per-stage |

The UI should provide:

1. An inherited/default option for each row.
2. A provider selector followed by a model/profile selector filtered by that provider's registered models.
3. Capability indicators for tools, structured output, context size, resume/fork, and local/cloud execution.
4. Cost and latency estimates clearly labeled as estimates, based on configured or measured usage.
5. Provider-specific effort controls only when supported.
6. A connection/configuration status that never exposes credentials.
7. “Apply for this session” and “Save to project” actions. Global defaults belong in the user's Q3TUI settings; design-specific routes belong in the project configuration.

Use a registry of configured models rather than fetching and exposing every available model ID without review. Model catalogs change, IDs may be preview aliases, and availability does not prove that the model supports the required tools or structured outputs.

The YAML remains the saved representation and expert override. Normal users select through the TUI; advanced users can edit YAML, and the TUI validates the same schema after loading it.

### Migration and compatibility

- Existing llm.model and llm.steps.<step>.model values should be migrated into a default Claude profile and per-step route overrides.
- Existing users must retain their selected model and effort after upgrade.
- If llm.backend is codex and an old Claude-specific step override exists, show a visible warning or offer a one-time route migration. Never ignore it silently.
- The UI should indicate that changes apply from the next stage, because a running provider request cannot safely change its model mid-turn.

## Recommendation 3: Route Each Step Deterministically

Resolve a model profile when a task is created, not halfway through its execution:

1. Read an explicit task override, if the flow declares one.
2. Otherwise read the active step route.
3. Otherwise use the role route if configured.
4. Otherwise use the project default profile.
5. Apply capability, security, and budget checks.
6. Freeze the resolved route into the task record.

Explicit per-step routes should be the default. A dynamic router that selects a model from quality/cost estimates can be a later opt-in policy. It must choose only from profiles that passed capability and data-policy checks, and record why it selected that profile.

Fallbacks must also be explicit. A fallback may handle temporary quota or provider failures, but the run record must show that the route changed. Never turn a failed high-quality review into an unmarked pass from a cheaper model.

## Recommendation 4: Add a Bounded Worker Scheduler

### Model-proposed plan, engine-controlled execution

A coordinator model may call a tool such as propose_tasks. Its output should be structured and limited to:

- task ID and purpose;
- input artifact references and hashes;
- dependencies;
- read and write sets;
- required result schema;
- proposed profile;
- estimated cost and time;
- completion checks.

The engine validates the plan before creating any worker. Validation must reject:

- missing or undeclared input artifacts;
- dependency cycles;
- overlapping write sets, unless a later merge task owns the shared files;
- a route lacking required capabilities;
- too many workers or a budget above policy;
- a task that crosses a step's denied-directory boundary;
- a task that attempts to approve its own gate.

### Worker lifecycle

Use explicit states:

    pending -> ready -> running -> result_received -> validated -> merged
                                  |                    |
                                  +-> failed           +-> needs_review
                                  +-> cancelled

Persist each transition before reporting it to the TUI. A worker result is not complete merely because the model stopped generating text.

### Isolation and writes

Give each worker:

- a unique task ID and run ID;
- an immutable task brief and input artifact hashes;
- a provider/model profile frozen for the task;
- an isolated workspace or a strict file write set;
- only the tools required for that task;
- token/cost, wall-time, and turn budgets;
- a structured output schema.

For workers that edit RTL or other shared deliverables, use separate worktrees or task directories. Enforce one writer per file. Merge through a deterministic step that checks file collisions and validates dependencies. Avoid letting multiple sessions edit the same shared project folder.

### Scheduling, retries, and cancellation

- Use a provider-specific semaphore and a global maximum worker count.
- Respect provider rate limits with bounded exponential backoff and jitter.
- Assign idempotency keys derived from run ID, task ID, input hashes, and route.
- Retry only transient failures. Invalid results get a bounded repair attempt with the validation errors; permission failures and design conflicts go to review.
- Cancellation must stop new workers, request interruption of active workers where supported, and preserve completed outputs.
- Maintain aggregate per-run limits for cost, tokens, time, and worker count.

### Fan-in

The fan-in step validates every worker result against its schema and declared write set. It then:

1. checks required tasks completed;
2. verifies output hashes and provenance;
3. detects conflicting edits or incompatible assumptions;
4. merges only non-conflicting artifacts;
5. runs static and EDA checks on the merged result;
6. creates a review report with unresolved conflicts and evidence.

The coordinator may summarize the combined output. It must not fabricate missing worker evidence or convert a failed deterministic check into a pass.

## Recommendation 5: Parallelize Only Independent Work

Suitable examples:

- RTL generation for modules with frozen interfaces and distinct output files.
- Test generation for independent test groups based on one approved verification contract.
- Independent read-only design reviews after a candidate artifact is frozen.
- Lint, elaboration, synthesis, and static checks that consume the same immutable snapshot.

Sequential dependencies include requirement approval before architecture generation, architecture/configuration approval before RTL, and RTL snapshot creation before RTL-dependent integration or implementation checks. Verification generation that is required to remain RTL-independent must receive only its approved specification and contract.

The engine should derive dependencies from the flow DAG and artifact hashes. A model may suggest additional decomposition, but it cannot remove declared dependencies.

## Recommendation 6: Define Consensus Through Evidence

Q3 stands for Quality, Quick, and Quorum. Treat quorum as a review relationship among engineer, AI, and tools, not as a majority vote among language models:

- Engineer: owns requirements, tradeoffs, and approval gates.
- AI models: draft, analyze, implement, and independently challenge within assigned roles.
- Tools: provide objective evidence through lint, elaboration, simulation, formal checks, synthesis, or reports.

For high-risk decisions, use a separate reviewer model with a fresh context and read-only access. Give it the specification, decision, and evidence; avoid feeding it the implementer's rationale before its first review when an independent assessment matters. Route disagreement to an engineer or to a targeted deterministic check.

Multiple model outputs are correlated and can repeat the same wrong assumption. Model agreement is supporting evidence, not a correctness criterion.

## Recommendation 7: Measure Quality, Latency, and Cost

Before enabling dynamic routing, build a replay set of representative Q3TUI tasks. Record:

- schema-valid result rate;
- requirement traceability;
- lint/elaboration/simulation/formal pass rate;
- number of repair loops;
- diff size and unintended changes;
- latency by step and provider;
- input/output/cached tokens and estimated cost;
- timeout, rate-limit, and fallback frequency;
- reviewer disagreement rate.

Compare model profiles on identical frozen inputs. Select profiles per task class only when results justify the added provider and maintenance complexity. Keep deterministic tools as the final pass authority.

## Implementation Sequence

### Phase 0 — Make current behavior clear

- Label the existing Models per step tab as Claude model routing.
- If the Codex backend is active, hide unsupported Claude IDs or show that they are inactive.
- Warn when a saved route is unsupported by the selected backend.
- Document that changes apply from the next stage.

### Phase 1 — Provider registry and static per-step routing

- Introduce provider/profile schemas and secret references.
- Add a provider adapter protocol around runtime.run_stage.
- Move model choices from a hard-coded global list to configured profiles and capability metadata.
- Extend TUI rows to select provider/profile per step.
- Preserve old Claude and Codex configuration through migration.
- Record the resolved profile in stage events and run history.

### Phase 2 — Deterministic worker pool

- Implement task records, state transitions, bounded concurrency, budgets, cancellation, retries, and result validation.
- Reuse existing independent module/test parallelism where practical.
- Isolate write tasks in separate workspaces and define one-writer-per-file rules.
- Add TUI views for task tree, worker model, state, cost, logs, and output artifact.

### Phase 3 — Coordinator-proposed decomposition

- Expose a narrowly scoped propose_tasks tool to selected coordinator stages.
- Validate its structured plan through the engine.
- Begin with a maximum worker count and conservative per-run budget.
- Require human approval before executing dynamic plans until the failure and cost data support an automatic policy.

### Phase 4 — Evidence-based routing improvements

- Use replay metrics to recommend model profiles for each step.
- Keep automatic profile changes opt-in and auditable.
- Add policy checks for local-only or approved-provider data handling.

## Risks and Controls

| Risk | Control |
|---|---|
| Workers overwrite each other's files | Separate worktrees, explicit write sets, one writer per file, merge validation |
| Coordinator creates excessive work | Maximum fan-out, per-run budgets, dependency/cycle checks, approval policy |
| Context differs between providers | Pass artifact references and a normalized task brief; treat sessions as provider-local |
| Provider lacks required tools or schema support | Capability validation before dispatch |
| Model says “pass” without proof | Deterministic checks and evidence schema are the pass authority |
| Different model versions change output | Record provider/model/version, prompt hash, input hashes, and adapter version |
| Sensitive RTL/spec is sent to an unapproved service | Data policy on profiles, visible TUI status, local-only route where required |
| Retry repeats a costly or unsafe operation | Idempotency key, retry classes, attempt caps, budget reservation |
| Consensus is mistaken for correctness | Independent reviewer plus deterministic evidence and engineer gates |

## Final Position

Q3TUI should expose model choice in the TUI and save the selected configuration in YAML. The current TUI already does this for Claude models per step; multi-provider selection and Codex per-step model routing need implementation.

Keep the engine as the authority for scheduling and gates. Let a model propose a task plan, then validate and execute it through a bounded worker scheduler. Persist project artifacts and task state independently from provider sessions. Use parallel workers only for tasks with disjoint inputs or write ownership, and base pass/fail on tool evidence and explicit review gates.

## References

- Q3TUI TUI settings: q3tui/core/settings.py and q3tui/core/ops.py.
- Q3TUI model routing: q3tui/core/config.py, q3tui/llm/runtime.py, and q3tui/llm/codex/runner.py.
- Q3TUI role sessions: q3tui/llm/roles.py and docs/spec/team.md.
- [Anthropic multi-agent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration) — provider example of separate agent threads and parallel workflows.
- [Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform) — guidance on integration layers for bounded tasks and applications that manage task lifecycle.
