---
label: "3"
title: ASIC memory macros
deps: [sdc, asic_port]
gate: human
options:
  pdk_root: null      # where the memory compilers / macros are; empty: the PDK folder of the asic_synth library (the parent with a MEMORY / SRAM folder)
  corner: null        # the macros' corner; empty: the standard-cell library's (…tt0p9v25c.db → tt0p9v25c)
  prefer: compiler    # compiler: a memory compiler of the PDK first (tool role mem_compile), then the pre-generated macros; macros: only those
  flops: []           # wrappers to keep as flip-flops
view: [schemas/asic_macro.json]
---
The memory wrappers of the RTL (`*_sram` / `*_rf` / `*_rom`, the ASIC port rule file's convention) become memory macros of the PDK. It runs
after the SDC: the clock period decides which macros are fast enough and goes to a memory compiler that takes one. For each wrapper: what it
holds (words, bits, its ports — an LLM stage, checked against the elaborated ports), then a memory compiler of the PDK when one is usable and
the tool role `mem_compile` is in config/tools.json, else the smallest rows × columns of one pre-generated macro that has the ports, the write
mask and the clock (code; the pins of a macro family from an LLM stage, checked against the Liberty pins), else flip-flops. Code writes the
ASIC body (`build/syn/asic/macros/<wrapper>.sv`: the wrapper's own header, the macros, the row decode, the write mask, the read mux),
turns the macros' `.lib` into `.db` (Library Compiler, tool role `lib_compile`) and checks the body against the behavioural wrapper in
lock-step (tool roles `sim` + `run`). `asic_synth` and `asic_lec` read the bodies instead of the behavioural files, and the `.db` in their
link libraries; `src/rtl/` is never changed.

<!-- SPEC -->
You describe the memory a wrapper module of an RTL design holds, for the engineer who replaces its body with SRAM / register-file / ROM
macros. Read the wrapper's file. The ports and widths you are given are ground truth (as instantiated in the design): use those names only.
Say how many words the storage holds as instantiated (the array's depth with the parent's parameters; it may be less than the address
reaches), the word width, and each independent access port: its kind (rw: one address for read and write; r: read only; w: write only),
its clock, address, data in / out, its enable (chip or read enable; empty when every cycle accesses), its write enable, its byte / bit write
enables, and the polarity of each. The read latency is the number of clock edges from the address to the read data (a registered read is 1).
A ROM is a memory initialised from a file and never written. Put the read-during-write behaviour and anything else the macro body must keep in
`notes`, in one sentence. Do not invent ports; do not describe logic outside the storage.
<!-- /SPEC -->

<!-- PINS -->
You map the pins of a memory macro of a standard-cell PDK (SRAM, register file, ROM from a memory compiler) to their functions, for code that
instantiates it. The pins and widths you are given come from its Liberty file: use those names only. Read its Verilog model (the header
comments list the pins; the logic shows the polarities). For each functional port of the macro (one per independent address: rw, r or w)
give the clock, the address bus, data in, data out, the chip / port enable, the write enable and the bit write enable bus, and whether each
enable is active low (TSMC: CEB, WEB, BWEB are active low). Every other input pin — test and BIST muxes (…M pins, BIST), sleep (SLP),
shut-down (SD), margin / timing adjust (RTSEL, WTSEL, …), redundancy, power-gating — goes in `ties` with the constant that gives normal
operation (BIST 1'b0 selects the functional pins; SLP / SD 1'b0; a margin bus its documented default). Every input pin is either mapped or
tied. Never leave one out.
<!-- /PINS -->

<!-- COMPILER -->
You judge the memory compilers of a PDK for Q3TUI's ASIC flow. You are given the executables found under the PDK's memory folders and one
memory to make. Read the kits around them (the installation guide, the user guide, the release notes, the config examples; PDFs can be
read) and find out whether a compiler here can make this memory for this technology: the engine alone is not enough — it needs the
compiler's data (its .mco / config / database) for the memory type. `usable` is true only when everything it needs is there. When it is:
give the command line for the tool role (with {config}: the input file you write, and {workdir}: where it writes its views; the role is the
user's to add to config/tools.json), the input file for this memory (words, bits, mux, write mask, the clock target when it takes one),
and where the corner's .lib, the Verilog model and the LEF land (globs relative to {workdir}). When it is not, say exactly what is missing.
You never run anything.
<!-- /COMPILER -->

<!-- REVIEW -->
You review the memories of Q3TUI's ASIC flow that ended up as flip-flops although they are large. For each wrapper you get what it is, the
notes of the code that chose the macros (every macro family it rejected and why) and the pin maps it kept. Code checks are strict and can
be wrong: a reason that is false (a valid Verilog constant called invalid, a pin that does exist, a polarity read the wrong way) is
`check_wrong` — name the macro that should be used (the cell name in the notes; the smallest that fits). A reason that is true but would go
away with a change of the design (a combinational read where a registered one would do, more ports than any macro has, a word that is
not a power of two) is `mismatch` — say the change as a spec change request, by function, ports and latency, never by macro or cell name.
Flip-flops that are right (no macro of the PDK can be this memory and the design should not change) are `intended`. Read the Liberty
files and the Verilog models where a reason needs it. Be short: the explanation is what the designer reads in the question.
<!-- /REVIEW -->
