# Workspace & state

Status: **settled**.

What Q3TUI owns on disk: the `.q3tui/` folder of a project, its own part of
`$Q3TUI_HOME`, and how a project is recognised. Where the flows write is decided by the
flows (Flow definitions).

## The project

- A project is a folder that has `.q3tui/`. Q3TUI finds it from the current folder,
  going up through the parent folders (as git finds `.git/`). When none is found, Q3TUI
  creates `.q3tui/` in the current folder, which becomes the project (and adds its lines
  to `.gitignore`, below).
- Everything outside `.q3tui/` is decided by the flow: what the steps write
  (`outputs[].path`) and the user files they read (`inputs[].path`). Q3TUI creates no other
  folder and defines no standard layout; `src/`, `reports/`, … are conventions of the flow
  repository.
- **Import.** Q3TUI's core does not bring your existing files into a project: it knows
  no artifact. A step that takes user files registers an importer in its addon, which
  knows its own `inputs[].path` (Extensibility, "Importers").
- When it creates a project, Q3TUI adds to `.gitignore` only what is its own:
  `.q3tui/state/`, `.q3tui/sites/` and `.q3tui/packages/`.

## Sites

What is downloaded from outside lives in a `sites/` folder and is recorded in a
`sites.yaml` next to it, in the same form at both levels:

| File                           | Records                                                         | Committed |
| ------------------------------ | --------------------------------------------------------------- | --------- |
| `$Q3TUI_HOME/sites.yaml`       | the sites installed in the home: flow repositories, packages of steps | —    |
| `<project>/.q3tui/sites.yaml`  | the project's sites: vendor sources (IP) the design uses        | yes       |

```yaml
vlsit-flows:
  source: {git: "https://…/vlsit-flows.git", ref: v2.1.0}   # a tag or a commit
  links: [flows/vlsit, stages/rtl, steps/smoke]            # the links Q3TUI made
apb-csr-generator:
  source: {git: "https://…/APB-CSR-Generator.git", ref: v1.2}
  links: [packages/apb-csr-generator]
```

- Q3TUI writes `sites.yaml` when it installs, updates or removes a site. The `sites/`
  folders are not committed.
- A site that the project's `sites.yaml` lists but that is not downloaded is reported
  ("site not fetched"); it is downloaded only when you ask, after its `source` is shown.
- How vendor sources are arranged into the design (links under the design's folders, a
  place for your changes) is the flow's work (a step or a skill); Q3TUI only downloads,
  records and links.

## `.q3tui/`

```text
.q3tui/
  config.yaml          the project layer of the config                           committed
  sites.yaml           the project's sites                                       committed
  decisions.yaml       the questions, their answers and their history (Engine)   committed
  flows/ stages/ steps/ skills/ templates/ rules/ knowledge/   the project's own files (Flow definitions)   committed
  packages/            links to packages on this machine                         not committed
  sites/               the downloaded sites                                      not committed
  state/                                                                         not committed
    pipeline.json      written once the flow has run (its presence tells a project that has
                       run, TUI): the state of each step: result, origin, the hash of each input and
                       output, the hash and version of its definition, its approval (by whom,
                       when), its change requests, its fix loop counter, its review items, its cost;
                       and the total cost with the audit of its resets
    sessions/<step>/   the LLM session of each step (LLM runtime)
    assistant/         the assistant's session (Assistant)
    events.jsonl       every event of the project, in or out of a run (Engine)
    backups/           the backups: of a reset, of edited outputs before an update, of a
                       step's outputs when it starts, of the outputs a best round replaces
    loop/<step>/best/  the best round of a step's fix loop
    work/<step>/       the working folder of the step's tools (Tools / EDA)
    cache/             the checkpoints of LLM tasks, for resuming (LLM runtime)
    tui/               the TUI's layout and input history
    lock               the lock between processes (Engine)
```

- Your decisions (questions and answers) are committed with the project, so that a
  teammate who clones it is not asked again. Everything in `state/` belongs to this
  machine and is not committed.

## `$Q3TUI_HOME`

```text
$Q3TUI_HOME/                   (default ~/.q3tui)
  config.yaml                  the user layer of the config
  sites.yaml                   the installed sites
  sites/                       the downloaded sites
  flows/ stages/ steps/ skills/ templates/ rules/ knowledge/ packages/
                               links into sites/ (or real folders and files of your own)
  approvals.yaml               the project commands and code you allowed (Configurations, Extensibility)
```

- `approvals.yaml` records, per project: the project's path, the kind (command or code),
  the hash, and when it was allowed. Allowing something in one project does not allow it
  in another.
- Q3TUI keeps nothing else in the home: the state of a project is in its own
  `.q3tui/state/`.
