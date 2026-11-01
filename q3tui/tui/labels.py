"""How a step's display state is shown: its label, colour and icon (spec/tui.md "Display states")."""

from __future__ import annotations

from textual.content import Content

from q3tui.engine.engine import StepStatus
from q3tui.tui.ui.icons import IconName, icon

# display state -> (label, style, icon)
DISPLAY: dict[str, tuple[str, str, IconName]] = {
    "running": ("running", "$primary", "step_running"),
    "failed": ("failed", "$text-error", "step_failed"),
    "missing_input": ("missing input", "$text-error", "step_blocked"),
    "question waiting": ("question waiting", "$text-warning", "step_gate"),
    "stale": ("stale", "$text-warning", "warning"),
    "approval waiting": ("waiting for approval", "$text-warning", "step_gate"),
    "approved": ("approved", "$text-success", "step_done"),
    "done": ("done", "$success 70%", "step_done"),
    "pending": ("pending", "$text-muted", "step_pending"),
}


def marks(st: StepStatus) -> list[str]:
    """The marks shown next to the label."""
    out = []
    if st.origin == "user":
        out.append("yours")
    if st.edited:
        out.append("edited")
    if st.definition_changed:
        out.append("definition changed")
    non_blocking = st.open_questions - st.blocking_questions
    if non_blocking:
        out.append(f"{non_blocking} question{'s' if non_blocking > 1 else ''}")
    if st.pending_reviews:
        out.append(f"{st.pending_reviews} not reviewed")
    return out


def state_content(st: StepStatus, *, with_marks: bool = True) -> Content:
    label, style, name = DISPLAY[st.display]
    parts: list = [(f"{icon(name)} {label}", style)]
    if with_marks:
        for m in marks(st):
            parts += [(" · ", "dim"), (m, "$text-muted")]
    return Content.assemble(*parts)


def state_icon(st: StepStatus) -> Content:
    _, style, name = DISPLAY[st.display]
    return Content.styled(icon(name), style)
