"""Add-on of the ASIC flow (q3tui/addons.py): the SDC actions (the FPGA flow's: both work on `constraints/sdc/`), the library and target
settings of the synthesis, and `asic_handoff`: the ASIC port findings to the flow that owns the RTL."""

from __future__ import annotations

from q3tui.flows.fpga import addon as fpga_addon


def _handoff(ops, ids: str) -> str:
    """Send the ASIC port findings to the flow that owns the RTL: an order that makes a wrapper module goes to its spec step (a new module is a
    change of the design hierarchy: spec → parse → the rtl step's plan; all of them in one request), the rest to its rtl step, one scoped
    change request each."""
    from datetime import datetime

    from q3tui import flows
    from q3tui.flows.asic.lib import port
    from q3tui.flows.asic.lib.base import PORT_JSON
    from q3tui.pipeline.engine import Engine, EngineError

    step = next((s for s in ops.engine.steps if s.kind == "asic.asic_port"), None)
    if step is None:
        raise EngineError("this flow has no asic_port step")
    data = step.read(ops.engine, PORT_JSON, {}) or {}
    wanted = {i.strip() for i in ids.split(",") if i.strip()}
    todo = [f for f in data.get("findings", []) if not f.get("handed_off") and (not wanted or f["id"] in wanted)]
    if not todo:
        raise EngineError("no finding to hand off (run asic_port first, or they were handed off already)")
    owner = flows.load_flow(str(step.options.get("handoff_flow") or "rtl"), ops.project.root)
    if owner.name == ops.engine.flow.name:
        raise EngineError("handoff_flow is this flow itself")
    ops.engine.save()
    other = Engine(ops.project, flow=owner)
    by_step: dict[str, list[dict]] = {}
    for f in todo:
        by_step.setdefault(port.handoff_step(f), []).append(f)
    for name in by_step:
        if name not in other.by_name:
            raise EngineError(f"flow '{owner.name}' has no step '{name}' to hand the findings to")
    at = datetime.now().isoformat(timespec="seconds")
    if "spec" in by_step:
        other.request_change("spec", port.spec_text(by_step["spec"]))
    for f in by_step.get("rtl", []):
        other.request_change("rtl", port.handoff_text(f))
    for name, fs in by_step.items():
        for f in fs:
            f["handed_off"] = {"flow": owner.name, "step": name, "at": at}
    step.write(ops.engine, PORT_JSON, data)
    ops.engine.reload()
    rec = ops.engine.state.steps.get(step.name)
    if rec is not None:  # (the hand-off is recorded in the findings: not a user edit of the step's output)
        rec.outputs = ops.engine._hash_files(step.outputs(ops.engine))
        ops.engine.save()
    sent = "; ".join(f"{', '.join(f['id'] for f in fs)} → {owner.name}:{name}" for name, fs in by_step.items())
    return ops._log(step.name, f"ASIC port: handed off {sent}; run flow '{owner.name}' to apply them (q3tui --flow {owner.name} run)")


def register_estimate(api) -> None:
    """The quick Fmax estimate (the FPGA flow registers it too: it is asked where the frequency is typed)."""

    @api.action("asic_estimate", "Estimate, in about a minute, the clock frequency the ASIC library allows for this RTL: Design Compiler at low effort "
                "with only the clocks constrained (register-to-register, no I/O). The result is shown next to each clock in the SDC tab and in sdc_set's "
                "answer; the full asic_synth is the exact number.")
    def asic_estimate(ops) -> str:
        from q3tui.flows.asic.lib import estimate

        return estimate.run(ops)


def register(api) -> None:
    api.setting("asic_synth", "library", "Library (.db)", "text",
                "The standard-cell library Design Compiler maps to: the .db file (a list in q3tui.yaml for several). Formality reads the same.")
    api.setting("asic_synth", "compile", "Compile command", "text", "compile_ultra, compile_ultra -gate_clock, compile -map_effort high, …")
    api.setting("asic_synth", "min_slack_ns", "Min setup slack (ns)", "float", "The review fails when the worst slack is below this.")
    api.setting("asic_synth", "max_area_um2", "Max area (µm²)", "float", "The review fails above this area; empty: no budget.", nullable=True)
    api.setting("asic_port", "min_mem_words", "Smallest memory worth a finding (words)", "int",
                "Unpacked arrays of at least this many words are reported as memories without a macro.")
    api.setting("asic_port", "handoff_flow", "Hand findings to flow", "text", "The flow that owns the RTL ((default rtl)).")
    api.setting("asic_macro", "pdk_root", "PDK folder of the memories", "text",
                "Where the memory compilers and macros are; empty: the PDK folder of the library (the parent with a MEMORY / SRAM folder).", nullable=True)
    api.setting("asic_macro", "corner", "Macro corner", "text", "The memory macros' corner (tt0p9v25c, …); empty: the library's.", nullable=True)
    api.setting("asic_macro", "prefer", "Memory source", "choice", "A memory compiler of the PDK first (tool role mem_compile), then the pre-generated macros; or only those.",
                choices=(("compiler", "compiler, then macros"), ("macros", "pre-generated macros only")))

    @api.action("asic_handoff", "Hand the ASIC port findings (FPGA primitives, memories without a macro, power-up values, …) to the flow that "
                "owns the RTL: an order that makes a wrapper module goes to its spec step (one request for all of them), the rest to its rtl "
                "step as scoped change requests. That flow then updates the RTL (run it); this flow's checks "
                "run again on the new RTL.",
                {"ids": "finding ids separated by commas (P1,P2); empty: every finding not handed off yet"}, optional=("ids",))
    def asic_handoff(ops, ids: str = "") -> str:
        return _handoff(ops, ids)

    @api.action("asic_waive", "Waive something the ASIC synthesis report flags, with a reason (kept in reviews/asic_synth_waivers.json): a constraint group "
                "(what=group, key=min_delay/hold; max_ns: waived only up to that many ns of violation), one violation (what=item, key=<group>:<endpoint>) "
                "or a warning code (what=code, key=LINT-28). A waived violation no longer fails the verdict; asic_synth scores its reports again "
                "on the next run (no new synthesis).",
                {"what": "group | item | code", "key": "the group, <group>:<endpoint> or the code", "reason": "why it is fine",
                 "max_ns": "group only: the largest violation (ns) the waiver covers; empty: all"}, optional=("reason", "max_ns"))
    def asic_waive(ops, what: str, key: str, reason: str = "", max_ns: str = "") -> str:
        from q3tui.flows.asic.lib import waivers

        return waivers.add(ops.project, what, key, reason, float(max_ns) if str(max_ns).strip() else None)

    @api.action("asic_unwaive", "Remove a waiver of the ASIC synthesis report (the key it was given: min_delay/hold, <group>:<endpoint>, LINT-28).",
                {"key": "the waived group, item or code"})
    def asic_unwaive(ops, key: str) -> str:
        from q3tui.flows.asic.lib import waivers

        return waivers.remove(ops.project, key)

    register_estimate(api)
    fpga_addon.register_sdc(api)
