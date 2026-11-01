# TUI

Status: **settled**, except the items under "Open items"; "Keys and buttons" is
provisional.

The terminal interface (Textual). It acts only through Ops and shows what the engine's
events and state say (Engine).

## Components

The TUI uses its library of components ported from shadcn first, and a
component of its own only where none fits (for example the Questionnaire of the chat).

## Layout

Every screen:

```text
┌ title bar ──────────────────────────────────────────────┐
│                     (one empty row)                     │
│                     the main part                       │
│                     (one empty row)                     │
└ status bar: status · keys of the moment · current folder┘
```

- One empty row between the main part and the title bar, and one between the main part and
  the status bar.
- The status bar shows the status, what has the focus (`Flow ▸ spec`, `Main ▸ spec ▸ Log`,
  `Activities`, `Alerts ▸ 2/8`), the keys that apply there, and the current folder.
- The status is always there, first, as `● <status>`, the dot in the status's colour:
  `idle` grey, `running` primary, `stopping` and `waiting for you` yellow, `failed` red.

### Home

The brand and the input box, and the alerts (see "Alerts"); no row of suggested examples.

- Its input box writes the flow's first user file that a step requires (an input with
  `path`, Flow definitions): `spec/intent.md` for a flow whose first step needs it. When the
  file exists already (a project that has not run yet), the box shows its text to edit, and
  Enter saves it. A flow with no such input has no input box on Home.

### Workspace

Built with the resizable component:

```text
┌ title bar ───────────────────────────────────────────────┐
│ sidebar           │ Main (the step in view)              │
│  [Assistant|Flow] │                                      │
│                   ├──────────────────────────────────────┤
│                   │ panel: Activities                    │
└ status bar ──────────────────────────────────────────────┘
```

- The sidebar has two tabs: **Assistant** and **Flow**. The tab in view and the focus always
  agree: showing a tab (a click, its key) puts the focus in it, and a focus that goes into the
  other tab shows it.
- The panel below Main shows **Activities**, under a title line "Activities" (plain bold text,
  like the title of a Card, no background) that does not scroll. It is always there: it is never hidden.
- **The conversation** of the Assistant tab: each message of the user in a Bubble on the right
  (at most 80% of the width); each answer as Markdown across the whole width, with no frame,
  avatar or name, drawn like a Markdown view of Main (see "Main": diagrams, code blocks); a
  tool call as one faint line (the tool and its main argument); errors and warnings as one
  coloured line.

### Which screen opens

- A project that has run before opens in the Workspace. It has run when it has the engine's
  state file, `.q3tui/state/pipeline.json` (Workspace & state): the events written outside a
  run (a toast, a download) also create `.q3tui/state/`, and do not count.
- A project that has never run opens on Home.
- File → New project picks or makes a folder, which becomes the current folder: as it has
  no `.q3tui/`, one is created there (Workspace & state) and it opens on Home. File → Open
  project opens the chosen folder by the same rules.

### Main with no step in view

Main shows the Empty component (a short message that says to pick a step in the Flow tab).
The assistant then works with no step in view (Assistant).

### Settings

```text
┌ title bar ───────────────────────────────────────────────┐
│ sidebar           │ settings                             │
│  Assistant        │                                      │
└ status bar ──────────────────────────────────────────────┘
```

- The sidebar holds the Assistant, hidden when the screen opens; View ▸ Assistant (a check
  item) shows or hides it. The rest is the settings (see "Settings").
- The screen is drawn at once, a tab of the settings showing a skeleton while its rows are
  built; a tab is built the first time it is shown, not before.

## Alerts

Every use of the Alert component has one form:

```text
⚠ Tool `sim` is not configured
  Needed by: smoke, simulate. Set its command in tools.roles.sim.
```

| Part     | What                                                                  |
| -------- | --------------------------------------------------------------------- |
| severity | `error` (cannot run), `warning` (runs, something is missing), `info`  |
| title    | one line: what the problem is                                         |
| detail   | one line: what it affects and where to fix it                         |
| action   | optional: what the alert does when you choose it (open the settings, the dialog of [Install] or [Fetch site], …); it has no button |

- The alerts of one place have the same width (on Home, the width of the input box), one
  under the other, apart by their own edges (no empty row between them).
- **Mouse:** a click on an alert does its action.
- **Keys:** the alerts of a place are one list, one of the parts Tab moves between (see
  "Focus"). While it has the focus one alert is always chosen (the first, at first); Up / Down
  choose another, Space does its action.

Home shows these alerts, the most severe first:

- each error of the flow;
- each required tool, package or asset that is missing;
- each site of the project that is not fetched;
- each unknown key of the config (a warning).

Other places pick the component that fits them (a toast, a line of Main, a dialog); when
they use an Alert, it has this form.

## Display states

The Flow tree and Main show a step's display state (Engine) with the same labels and
colours:

| Display state    | Label                  | Colour      |
| ---------------- | ---------------------- | ----------- |
| running          | `running` (a spinner)  | blue        |
| failed           | `failed`               | red         |
| missing_input    | `missing input`        | red         |
| question waiting | `question waiting`     | yellow      |
| stale            | `stale`                | yellow      |
| approval waiting | `waiting for approval` | yellow      |
| approved         | `approved`             | green       |
| done             | `done`                 | light green |
| pending          | `pending`              | grey        |

- Marks next to the label: `yours` (origin user), `edited`, `definition changed`, the
  number of open non-blocking questions, the number of review items not reviewed.
- A colour is never alone: a label or an icon always goes with it.

## Dialogs and notifications

| When                                                          | Component                                    |
| ------------------------------------------------------------- | -------------------------------------------- |
| you answer a question                                         | Dialog with the Questionnaire (the question's options, the default marked, and a last choice "Something else" you type in) |
| you send a change request                                     | Dialog with a Textarea; Ctrl+S sends         |
| a step's definition changed (when Q3TUI opens a project, Engine) | Dialog listing the steps and versions: [Run again] [Later] |
| a destructive action you asked for (a reset, a regenerate, a forced approval) | AlertDialog: [Confirm] [Cancel] |
| a command or code of the project is about to run for the first time (Configurations, Extensibility) | AlertDialog showing the command or file: [Allow] [Deny] |
| a package or a site is about to be downloaded                 | AlertDialog showing its `source`: [Download] [Cancel] |
| the assistant needs your OK or an answer                      | a card in the chat (Alert or Questionnaire)  |
| something passing: an approval refused, an action's result, a run that ended | Toast, also written to Activities |

- A Dialog asks you to enter or pick something; an AlertDialog asks only yes or no about
  something serious, and is not dismissed by clicking outside it.
- Only what needs your decision now blocks; everything else is a toast.
- Toasts shown together stack one under the other, apart by their own edges (like the
  alerts, no empty row between them).
- A gate that waits opens no dialog: the step shows `waiting for approval` and a toast says
  so. You approve from Main (see "Main").

## Main

```text
smoke
⏸ waiting for approval · 2 not reviewed · stage rtl           [Approve] [Change]

 smoke_report   Questions 1   Log

▸ test_reset      ok        │ test_overflow
  test_overflow   failed    │ Expected full=1 at cycle 18, got 0 …
  test_flush      not rev.  │
```

- **The header** is two lines. The first is the step, its title (bold, like the title of a
  Card). The second is its display state with its marks (see "Display states") and its
  stage, with the buttons of the step's main actions on the right, which depend on its
  state. A blank line, the tabs, a blank line, then the content of the tab.

  | Display state                   | Buttons               |
  | ------------------------------- | --------------------- |
  | waiting for approval            | [Approve] [Change]    |
  | question waiting                | [Answer]              |
  | stale, pending                  | [Run] (run to this step) |
  | failed, missing input           | [Run] [Log]           |
  | approved, done                  | [Change]              |
  | running                         | none (Ctrl+X stops)   |

- **The tabs:** one per output that has a view, in the order of `outputs`; `Questions n`
  when the step has questions; `Log`.
- **A view tab** with items (`sections`, `table`, `files`) is a list and a detail, split by a
  divider of the resizable component; a `document` takes the whole width.
- A `table`'s list shows the first three of its `columns`, lined up under a header of their
  titles (a column's `title`, else its field) that stays in place while the rows scroll.
- **The Log tab** shows only the events of the step in view, from every run and from
  outside runs, each with its time (read from `events.jsonl`). Activities shows the events
  of the run going on and the events outside runs of this session.
- Both draw the events the same way. A run of a step is **one line** (the TraceLine
  component): a spinner while it runs, then its result, cost and turns on the same line. Its
  LLM work (each task, its text, its tool calls, the tool's progress lines) folds under that
  line: open while the step runs, closed when it is over; Enter or a click opens or closes it.
  In the Log tab every run starts closed; while the step in view runs, the Log updates and
  keeps the runs you opened open and the place you scrolled to. A stage starts and ends with a separator (the
  Marker component) that names it (and its outcome). The other events are one line each.
- In a Markdown view (a `document`, the detail of an item), a ```mermaid block (flowchart,
  block diagram, state machine) and a ```wavedrom block are drawn as diagrams; one that
  cannot be drawn shows its source. A click on a diagram (or Enter on it) shows it larger
  in a Dialog, where the arrows scroll it.
- Any other code block has a header line: its language on the left, "copy" on the right; a
  click on "copy" copies the code and a toast says so. The same in the answers of the
  Assistant.
- No line of key hints: the status bar shows them.

## Keys and buttons

Provisional: kept as below until it has been built and used, then revisited.

### Focus

- A screen opens with the focus on its main part: the input box of Home (its alert list when
  it has no input box), the Flow tree of the Workspace (the selected step, else the first),
  the first setting of the Settings tab in view.
- Tab and Shift+Tab move the focus from one part of the screen to the next or the previous;
  that is all they do. The parts, in order: the title bar (its menus), then Home: the input
  box, the alert list; Workspace: the sidebar tab in view, Main, Activities; Settings: each
  field, in order. A part takes the focus back where it had it; Main takes it on the chosen
  row of the list in view (the buttons of its header are reached by their keys or the mouse).
- Escape on the title bar, with no menu open, takes the focus back to the main part (with a
  menu open, it first closes the menu).
- The focus shows the same way everywhere: the row or item that has it on a lighter
  background, never a border around the part. A list without the focus keeps its chosen row
  on a fainter background (the Flow tree, the lists of Main, the alerts).

### Rules

1. Global keys use Ctrl, Alt or F and work everywhere, typing included.
2. One-letter keys work only when the focus is not in a text field, and act on the step in
   view (or the row selected in the Flow tree).
3. Shift is "stronger": `c` confirms one item, `C` all; `a` approves, `A` by force.
4. A destructive or costly action (reset, regenerate) has no one-letter key: it is only in
   menus and the palette, and always asks with an AlertDialog.
5. Every action is in the command palette (Ctrl+K). The status bar shows only the keys of
   the part that has the focus, and only the ones that work there now (the keys of a step
   follow its state: `a` only while it waits for approval, `q` only while a question waits).
6. No combination that terminals often do not send (Ctrl+, , Ctrl+Shift+…).

### Input boxes

The input box of Home and the chat box of the Assistant tab take a pasted text of several lines
as one token, `[Pasted text #1 +11 lines]` (numbered from 1 in each box, the count being the
line breaks in the paste). Enter sends the text with each token replaced by what was pasted.
Backspace just after a token removes it whole. A paste of one line goes in as typed text.

A paste goes to the field that had the focus even when it comes while the terminal has lost the
focus (a terminal's paste confirmation dialog takes it until the paste is done).

### Global keys

| Key                         | Action                                               |
| --------------------------- | ---------------------------------------------------- |
| Ctrl+Q                      | quit                                                 |
| Ctrl+K                      | command palette                                      |
| Ctrl+R                      | run the flow                                         |
| Ctrl+X                      | stop the run                                         |
| Ctrl+N / Ctrl+O             | new project / open project                           |
| Alt+,                       | settings                                             |
| F1                          | keyboard shortcuts                                   |
| F6 / F7 / F8                | the flow / the model and effort (session layer) / the cost |
| Alt+F / Alt+R / Alt+V / Alt+H | the File / Run / View / Help menu                  |
| Alt+1 … Alt+9               | the 1st … 9th tab of the tab component around the focus: the sidebar (Assistant, Flow), Main (its outputs, Questions, Log), Settings (Session, Project, User); nothing where the focus is in no tabs. To go from one part of the screen to another: Tab |
| Tab, Shift+Tab              | move the focus to the next / previous part of the screen (see "Focus") |

### Keys on a step (focus not in a text field)

| Key           | Action                                                              |
| ------------- | ------------------------------------------------------------------- |
| `t` / `o` / `f` | run **t**o this step / **o**nly this step / **f**rom this step    |
| `s`           | run the **s**tage of this step                                      |
| `.`           | run this step again (`rerun`)                                       |
| `a` / `A`     | approve / approve by force (asks)                                   |
| `r`           | send the step a change request                                      |
| `q`           | answer the next open question                                       |
| `c` / `C`     | confirm the selected review item / every review item                |
| `w`           | ask for a change to the selected item                               |
| `m`           | ask the assistant about the selected item                           |
| Shift+F10     | the context menu of the row in the Flow tree (its [⋯])              |

### Keys in the Assistant tab

| Key                 | Action                        |
| ------------------- | ----------------------------- |
| Enter / Shift+Enter | send / new line               |
| Esc                 | stop the answer going on      |
| Ctrl+L              | new chat                      |
| `/`                 | the list of commands (below)  |

Ctrl+X stops only a run of the flow, never the assistant's answer.

**Commands of the chat box.** `/` lists every Ops action and every action of the flow's
steps' addons (the same list as the command palette), filtered as you type. `/<name>
key=value …` runs it at once, without the LLM, and its result shows as a line of the chat
(`/approve step=parse`, `/sdc_set key=clock_period value=5`).

### Buttons

**Title bar menus.**

- File: New project · Open project · Import… · Settings · Quit
- Run: Run flow · Stop · Gate mode ▸ `manual` / `auto` / `unattended` (session layer) ·
  Run changed steps again (after [Later] on a definition change)
- View: only what can be shown or hidden: Assistant (on Settings; a check item, unavailable
  where the Assistant is a tab of the sidebar)
- Help: Keyboard shortcuts · About

Next to them: Flow ▾, Model / effort ▾, and two costs:

- **session**: what the LLM spent since Q3TUI started, the steps and the assistant;
- **project**: what the project's runs and its assistant spent, until the cost is reset.

Each has its own tooltip saying which it is; F8 (shown after them), or a click on either,
opens one Dialog with the details (the
project and session totals, the assistant, each step that spent something) and [Reset cost] (which asks with an AlertDialog) and [Close].

**Flow tree.** Buttons show on the selected row only:

```text
▾ rtl                                  [▶] [⋯]
  ▸ rtl      waiting for approval      [▶] [↻] [⋯]
```

- A step: [▶] run to here · [↻] run again · [⋯] Run only · Run from here · Regenerate ·
  Reset (with the steps after it) · Reset only this step · Gate ▸ · Actions ▸ (the step's
  addon actions; the submenu only when it has some).
- A stage: [▶] run the stage · [⋯] Gate ▸ (for every step of the stage).
- [⋯] is a context menu (the ContextMenu component): it opens under [⋯], at the pointer on a
  right click, or under the row with Shift+F10. Gate ▸ marks the gate in effect (for a stage,
  only when its steps share one). Escape closes it and gives the focus back to the row.

**Assistant tab.** [Stop] and [New chat] at its top.

**Home alerts.** No button: a click on an alert, or Space on it, does its action (see "Alerts").

The buttons of a step's main actions are in the header of Main (see "Main").

## Settings

- Three tabs, in the order of the layers: **Session · Project · User** (Configurations). The
  screen opens on Project.
- A value chosen in the Project or User tab is saved at once to that file; [Reset] removes
  the key from that file only. A value in the Session tab is not saved and is gone when Q3TUI
  exits; each of its rows has [Save to Project] and [Save to User].
- Each row shows the value in effect and where it comes from: `session`, `project`, `user`
  or `default`.
- Each row is a Field: the key's name (a click on it puts the focus in its value), the value
  of this tab, edited in place (Enter saves; a Select for a choice or a bool), its buttons,
  and the key's description under them (from the config schema, the meaning Configurations
  gives). A value that is refused shows its reason under the field, in red, and keeps the
  text typed so that it can be fixed; nothing is written. A value saved shows a toast.
- Its groups follow the sections of the config: LLM · Pipeline · Tools · PDKs · FPGAs · MCP
  servers · TUI · Sites & packages (their state, with [Install] and [Update]).
- What belongs to a flow, a stage or a step (`steps.<id>.*`, `stages.<stage>.params`) is not
  in Settings: it will be edited in a screen of its own for editing a flow (Open items).
- Ctrl+F searches the keys, titles and descriptions.
- The Tools group has [Apply preset ▾], which lists the `templates/tools/*.yaml` found by
  the lookup and applies the one you pick (Tools / EDA, "Presets"); the same action is in
  the command palette. A Home alert about a tool has [Open settings], which opens this
  group.

## Look

- **Theme.** One theme, `vlsit-dark` (`tui.theme`, Configurations).
- **Icons.** `tui.icons`: Nerd Font glyphs (`nerd`, the default) or plain Unicode for any
  font (`unicode`). The palette (Ctrl+K, "Icons: nerd / unicode") changes them for this session
  (the session layer); to keep a choice, set it in Settings, User tab.
- **Padding.** Every panel (each pane of the resizable component: the sidebar, Main,
  Activities, the panes of Settings) has a padding of one cell on the left and the right; a
  pane that only holds other panes has none. A pane inside a panel (the list and the detail
  of a view tab, in Main) keeps one cell only toward its divider: at the outer edges the
  panel already gives it, so everything in Main lines up. Nothing inside a panel adds a left
  or right inset of its own; a component with a background (a tab, a button, an input, a
  bubble) keeps its own inner padding.
- **Scrollbars.** They look the same thickness both ways: the vertical one is one column; the
  horizontal one is one row whose thumb is drawn half a row high (a cell is about twice as tall
  as it is wide). Muted, lighter on hover, primary while dragged.
- **UI language.** English only.
- **Sizes.** The sizes of the areas, once dragged, are remembered per project in
  `.q3tui/state/tui/` (Workspace & state); they are not config.

## Errors

A config with an error stops Q3TUI before the TUI appears (Configurations). Otherwise:

| Error                                              | Where it shows                                                       |
| -------------------------------------------------- | -------------------------------------------------------------------- |
| a flow with errors, on Home                        | one Alert per error (see "Alerts")                                   |
| a flow with errors, in the Workspace               | Main lists the errors as Alerts instead of the Empty component; Ctrl+R and the run buttons do nothing but a toast "the flow has errors" |
| an unknown key in the config (a warning)           | a toast when Q3TUI opens, and an Alert on Home                       |
| a step that fails during a run                     | `failed` in the Flow tree and in Main, a toast, a line in Activities; the reason in the step's Log |
| a broken tool                                      | as a failed step; the reason says the tool, not the design, is at fault |

## Mouse

- **Click:** menus, dropdowns, tabs, Flow tree rows, the buttons ([▶] [↻] [⋯], [Stop],
  [New chat], the buttons of Dialogs), the alerts (their action), list items, the chips of the chat and
  their ×, the "copy" of a code block. A click outside a Dialog closes it, except an
  AlertDialog.
- **Right click:** the context menu, as [⋯] (on the Flow tree).
- **Drag:** the dividers between areas; their sizes are remembered (see "Look").
- **Scroll:** the wheel scrolls. In Activities and the chat, scrolling up stops following
  new lines, and [Latest] goes back to them.
- **Text selection:** text selected in an item's detail goes with the question when you
  press `m`.
- **Tooltips:** on the two costs and on icon buttons.
- Everything done with the mouse can be done with the keyboard.

## Open items

- A screen for editing a flow (custom flows, and the values of `steps.<id>.*` and
  `stages.<stage>.params`): later.
