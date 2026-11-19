# The ECO flow (`eco`)

A netlist ECO: a change asked by a requirement goes into the already synthesized netlist as a few netlist edits, not a new synthesis.
The flow is independent of the VLSI flows: its entry is a **modification requirement** (not an intent), and the spec and the RTL are
**modified**, not generated. Its inputs are an ORG RTL, an ORG netlist and the requirement (the asic flow's outputs by default, or your own
paths). Code: `q3tui/flows/eco/`. Tests: `tests/test_eco.py`.

```
requirement ─┐                      project mode only
ORG RTL ─────┼─ ref/ ─ EQ(1) ─► SPEC (AI) ─► RTL(F) (AI) ─► dv + Sanity ─► PATCH CMD (AI) ─► Post NETLIST (DC) ─► EQ(2) ─► STA (PrimeTime)
ORG netlist ─┘                                  ▲   ▲            │              ▲    ▲            ▲   │               │
                                                │   └ their RTL fixes (judged, smallest)  │            └── eq2 fail (you choose)
                                                └──────────────────────────────── eq2 fail ┘   DC refuses the patch      │
                                                                                                      setup fail: timing fix (AI)
```

Memory macros: when the asic flow implemented a memory wrapper with SRAM macros (`asic_macro`, `schemas/asic_macro.json`), EQ(1) and EQ(2) read
that wrapper as its ASIC body (`lib/base.py` `asic_view`, the project's file or its copy in `ref/`), and DC / Formality / PrimeTime get the macros'
`.db` with the library (`need_libraries`). An ECO that edits a memory wrapper itself is not seen by EQ (run asic_macro again first).

No NETLIST(F): the patch is written from the RTL diff and the ORG netlist. The `.svf` beside the ORG netlist (DC's guidance) is kept with
it and read by EQ(1) and EQ(2): without it Formality cannot match DC's register merges and FSM recoding. No check of the size of the Post
NETLIST against the ORG netlist.

## Two modes, and `ref/`

The mode follows from where the ORG RTL is (`eco_inputs`, `lib/ref.py`):

| | **project** — the project's own `src/rtl` (made by the VLSI flows) | **external** — a filelist from elsewhere ("fire-fighting") |
|---|---|---|
| `ref/<name>/` keeps | `spec/`, `src/`, `constraints/`, `schemas/` (without the ECO's own `eco_*`) + `netlist/` | `rtl/` (the files, flat) + `netlist/` |
| spec | `eco_spec` updates `spec/*.md` in place (not the intent) → `eco/spec.diff` | not touched (skipped) |
| RTL(F) | `src/rtl` itself, modified in place | a copy in `eco/rtl/` |
| dv + Sanity | `eco_verify` asks; yes: both must pass before `eco_patch` | not requested (skipped) |

- The name of `ref/<name>/` is asked (default: the top module; option `ref_name`). A name already taken gets the date and time:
  `ref/<name>_DDMMYYYY_HHMMSS`. `netlist/` holds the ORG netlist and the `.sdc` / `.svf` beside it; `rtl.f` lists the ORG RTL copies
  (project-relative). The later steps take every ORG artifact from there (EQ(1), the patch, Post NETLIST, EQ(2), STA).
- `eco/ref.json` points to it (name, path, mode, created, sources, the file map). It is written once per ECO and no reset deletes it (a step
  run again never snapshots a project the ECO already changed); `ref/` is never deleted by the flow. A new ECO: delete `eco/ref.json`.
- While a project-mode ECO is on (`eco/ref.json` with `mode: project`), the RTL fixes of the dv flow's triage (`rtl_bug`) and of the Sanity
  review (`fix_rtl`; `spec` decisions → `eco_spec`) go to the ECO flow's `eco_rtl` (`flows/dv/triage.py`, `flows/sanity/addon.py`,
  `ref.eco_owner`), never to the rtl flow's generator; the dv flow does not run the ECO flow within its own run (no recursion: `eco_verify`
  runs dv).

**The concerns of an AI change are your questions** (`eco_spec`, `eco_rtl`; `lib/base.py` `ask_concerns` / `concern_answers`). Each concern
the AI reports with its spec or RTL(F) change (something the requirement leaves open, a risk, an assumption) becomes a blocking question
(`ECOCSPEC<n>` / `ECOCRTL<n>`): "Keep the change" (Recommended) or "My answer: …" (typed). The flow waits for every answer. Your words go
back to the same step as a change request (the change is revised, its new concerns are asked again); "keep" changes nothing. Each answer
is used once (`concern_asks` in `schemas/eco_spec.json` / `eco_rtl.json`). Auto-answer keeps the change and logs each concern.

## Steps

| # | Step | Gate | What it does |
|---|---|---|---|
| 1 | `eco_inputs` | none | Asks: the defaults (`src/rtl/filelist.f`, `build/syn/asic/netlist/<top>.v`, `eco/requirement.md`) or your paths (`rtl=… netlist=… requirement=…`). Options `rtl` / `netlist` / `requirement` skip the question. The mode from the RTL; asks the ref name; snapshots the ORG design to `ref/<name>/` (once: an existing `eco/ref.json` on the same sources is kept). A missing requirement gets a template. → `schemas/eco_inputs.json` (`mode`, `ref`, `source`, `rtl` = the ref filelist, `netlist` = the ref netlist), `eco/ref.json` |
| 2 | `eco_eq1` | none | `schemas/asic_lec.json` equivalent, on the netlist the ref copy came from (same content), newer than it and the RTL: asks "use that result, or run EQ(1) again?". Otherwise asks "run EQ(1)?" (no: skipped). Formality on ORG RTL vs ORG netlist (both from `ref/`). Fail: an AI analysis in `eco/reports/eq1.md`, the step fails. |
| 3 | `eco_spec` | human | Project mode: from the ORG spec (`ref/<name>/spec/`), the AI edits `spec/*.md` in place for the requirement, the smallest change (requirement IDs kept, a changed one marked "(ECO)"; never `spec/intent.md`: put back if touched). → `eco/spec.diff`, `schemas/eco_spec.json` (`updated` / `unchanged`). A change request (your review, a Sanity `spec` decision) edits the current spec. External mode: `skipped`. The spec flow's `parse` / `config` take the new spec when dv runs again. |
| 4 | `eco_rtl` | human | Project mode: the RTL files are the ORG ones again (from `ref/`), then modified in place in `src/rtl`; external mode: the ORG RTL copied to `eco/rtl/` (with its `filelist.f`). First a read-only AI plan of the smallest change (no new flop / port / state / width, outside replicated logic, reuse existing logic; the spec diff is in its prompt). When the requirement or a change request prescribes a way and the plan finds a smaller one with the same function, a blocking question: the smaller change (Recommended; auto-answer takes it) / as asked / your own way (`schemas/eco_rtl_plan.json`). A request from dv / Sanity is judged first (caused by the ECO change? already in the ORG RTL? a testbench / spec issue?): a plan "No RTL change: …" keeps RTL(F) and records it (`declined` in `schemas/eco_rtl.json`). Then the AI edits only RTL(F), that change and nothing more. pyslang must parse it with no error the ORG RTL has not (one retry). → `eco/rtl.diff` (ORG in `ref/` vs RTL(F)), `schemas/eco_rtl.json`. A revision that changes nothing fails. |
| 5 | `eco_verify` | none | Project mode: asks "run dv and Sanity again?" (option `verify`; auto-answer: yes). Yes: the dv flow, then the Sanity flow (analysis; open violations → the review's hand-off, to `eco_rtl` / `eco_spec`) run within this step (their gates approved only in an unattended run). Both pass (every dv step done, no FAIL / ERROR / TIMEOUT / BLOCKED test; Sanity nothing open) → `passed`. A fix handed to `eco_rtl` / `eco_spec`: the fix loop updates them and this step runs again, up to `max_rounds`; a request `eco_rtl` declined while the check still fails, or the bound: the step fails for you. No / external mode: `skipped`. → `schemas/eco_verify.json` |
| 6 | `eco_patch` | human | Waits for `eco_verify` `passed` / `skipped`. The AI (read-only) writes Design Compiler netlist edits from the diff and the ORG netlist. Code checks every line against an allow-list (`create_cell`, `connect_net`, `size_cell`, … and the `get_*` queries inside `[]`; no `;`, braces, `exec`, `source`, files), and against the netlist: a library cell must be one the netlist already uses (no placeholder), a touched instance must exist, a new cell or net must get connected. Refused edits go back to the AI once with the reasons. → `eco/patch/eco_patch.tcl`. A new patch drops old timing fixes. A revision with the same edits fails. |
| 7 | `eco_apply` | none | Design Compiler (role `asic_synth`): read the ORG netlist, `link`, source the patch then `sta_fix_*.tcl` in order, `check_design`, write `eco/netlist/<top>.v` (Post NETLIST). DC errors: back to `eco_patch` with the error lines, up to `max_rounds`. A failing new timing fix is removed. |
| 8 | `eco_eq2` | none | Formality on RTL(F) vs Post NETLIST. Fail: the AI analysis (`eco/reports/eq2.md`: causes, owner, recommended fix) and a blocking question: the recommended fix / the other step / your own fix (typed; goes to the step the analysis names, or start with `patch:` / `rtl:`) / stop. Under auto-answer the recommended fix is sent without asking. Up to `max_rounds`. |
| 9 | `eco_sta` | none | PrimeTime (role `eco_sta`) on the Post NETLIST with `sdc` (default `ref/<name>/netlist/<top>.sdc`, else `constraints/sdc/sdc.tcl`): setup / hold paths, all violators, global timing → `eco/reports/sta_*.rpt`, `sta.md`, `schemas/eco_sta.json`. Only setup fails; hold is reported (before placement). Setup fail: the AI writes `eco/patch/sta_fix_<n>.tcl` (sizing / buffering, same allow-list), `eco_apply`, EQ(2) and STA run again, up to `max_rounds`. |

`max_rounds` (eco_verify, eco_apply, eco_eq2, eco_sta; default `pipeline.max_fix_iterations`) counts the hand-backs since the step last passed,
across runs (the human gates of `eco_spec` / `eco_rtl` / `eco_patch` end each run). At the bound the step fails and the count starts again.

Auto-answer (`pipeline.auto_answer`, a step's gate mode `auto_answer` in `pipeline.gate_modes`, or `--yes`) asks nobody: the first option of
each question is taken (defaults, `ref/<top>`, run EQ(1), the smaller change, run dv + Sanity, the recommended EQ(2) fix). Auto-approve alone
still asks.

## In the TUI

Every ECO step has two tabs before Files / Questions (`q3tui/flows/eco/panels.py`), read from `schemas/eco_*.json` and `eco/`:

- **Report**: the step's result as rows (item, value, a coloured status: pass / fail / check / skipped / waiting), the highlighted row's
  detail on the right: the requirement and the ORG files (eco_inputs), the Formality report or the AI advice (EQ(1), EQ(2)), the summary,
  each change, each concern and the diff against `ref/` (eco_spec, eco_rtl), the dv tests and the CDC / RDC reports (eco_verify), the netlist
  edits and how they work (eco_patch), the errors and check_design (eco_apply), the setup / hold paths and the violators (eco_sta).
- **ECO**: the whole flow, one row per step with its result in one line ("9/9 steps done · 2 with notes to read"); the highlighted step's
  rows on the right. "check" marks a step that passed with concerns (eco_spec, eco_rtl); each concern row says "answer <id>", "kept"
  or "sent back".

## Settings

`eco_inputs`: `library` (the `.db`, read by DC, Formality and PrimeTime), `top`, `rtl`, `netlist`, `requirement`, `ref_name`. `eco_eq1` /
`eco_eq2`: `message_filter`, `extra_tcl` (as `asic_lec`). `eco_verify`: `verify` (yes / no), `max_rounds`. `eco_sta`: `sdc`, `max_paths`,
`max_rounds`. `eco_apply`: `max_rounds`.

Tool roles: `asic_synth`, `asic_lec` (the asic flow's), `eco_sta` = `pt_shell -f {script}` (module `synopsys/primeTime`,
`q3tui/eda/presets/flows/eco.json`); `eco_verify` uses the dv and Sanity flows' own roles.

## Not done

Formality's own ECO (`create_eco_patch`, licensed separately); hold fixing; a check that the Post NETLIST changed only a little; the
external filelist's `+incdir` / `+define` in `ref/<name>/rtl.f`; the asic flow is not run again after a project-mode ECO (the Post NETLIST
is the new netlist). The tests use fake tools (`eco_verify` with stand-ins for the dv and Sanity flows).
