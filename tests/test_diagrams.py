"""Diagrams in a Markdown view (spec/tui.md "Main"): mermaid and wavedrom drawn, the source when they cannot be."""

from textual.app import App

from q3tui.tui.diagrams import draw
from q3tui.tui.widgets.markdown import DiagramDialog, DiagramFence, Q3Markdown


def test_wave_and_mermaid_are_drawn():
    wave = draw('{signal: [{name: "i_clk", wave: "p..."}, {name: "o_d", wave: "x=.x", data: ["D0"]}]}', "wavedrom")
    assert "i_clk" in wave and "D0" in wave and "0   1   2" in wave
    fsm = draw("stateDiagram-v2\n  [*] --> IDLE\n  IDLE --> BUSY : start\n  BUSY --> IDLE : done", "mermaid")
    assert "IDLE (reset)" in fsm and "BUSY" in fsm
    assert draw("this is not mermaid {{", "mermaid") is None
    assert draw("module m; endmodule", "systemverilog") is None


class Viewer(App):
    def compose(self):
        yield Q3Markdown("# T\n\n```mermaid\nflowchart LR\n  a[Reader] -->|data| b[Writer]\n```\n\n```sv\nmodule m;\n```\n")


async def test_markdown_draws_and_enlarges():
    app = Viewer()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.3)
        fences = list(app.query(DiagramFence))
        assert [f.art is not None for f in fences] == [True, False]
        fences[0].focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DiagramDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DiagramDialog)
        await pilot.click(DiagramFence)  # one click is enough
        await pilot.pause()
        assert isinstance(app.screen, DiagramDialog)
