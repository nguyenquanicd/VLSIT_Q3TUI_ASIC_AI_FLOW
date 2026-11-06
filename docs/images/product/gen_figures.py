"""Vẽ các hình của docs/Q3TUI_Product_Description.docx (matplotlib, font Times New Roman như Handbook)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch, Polygon

for f_ in ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf", "consola.ttf"):
    p_ = os.path.join(r"C:\Windows\Fonts", f_)
    if os.path.exists(p_):
        fm.fontManager.addfont(p_)
plt.rcParams["font.family"] = "Times New Roman"

OUT = os.path.dirname(os.path.abspath(__file__))
PURPLE, DARK, GREY, RED = "#7030A0", "#323E4F", "#595959", "#C00000"
STY = {  # fill, edge
    "llm": ("#EBDDF5", PURPLE),    # có LLM stage
    "code": ("#DEE6F0", DARK),     # code tất định
    "tool": ("#FFF2CC", "#7F6000"),  # chạy EDA tool
    "gate": ("#FBE4D5", "#C55A11"),  # gate / quyết định
    "plain": ("#FFFFFF", DARK),
    "bar": ("#F2F2F2", GREY),
}
W_IN = 6.4


class Fig:
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.fig = plt.figure(figsize=(W_IN, W_IN * H / W))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, W)
        self.ax.set_ylim(H, 0)
        self.ax.axis("off")

    def box(self, x, y, w, h, text, kind="plain", fs=8, bold=False, align="center"):
        fc, ec = STY[kind]
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2", fc=fc, ec=ec, lw=1.0))
        if text:
            tx = x + w / 2 if align == "center" else x + 1.5
            self.ax.text(tx, y + h / 2, text, ha=align, va="center", fontsize=fs,
                         fontweight="bold" if bold else "normal", color="black", linespacing=1.15)
        return (x, y, w, h)

    def title(self, x, y, text, fs=8.5, color=PURPLE):
        self.ax.text(x, y, text, fontsize=fs, fontweight="bold", color=color, ha="left", va="center")

    def text(self, x, y, text, fs=7.5, ha="center", color="black", italic=False, bold=False):
        self.ax.text(x, y, text, fontsize=fs, ha=ha, va="center", color=color, linespacing=1.15,
                     fontstyle="italic" if italic else "normal", fontweight="bold" if bold else "normal")

    def diamond(self, cx, cy, w, h, text, fs=7.5):
        fc, ec = STY["gate"]
        self.ax.add_patch(Polygon([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)],
                                  closed=True, fc=fc, ec=ec, lw=1.0))
        self.text(cx, cy, text, fs=fs)

    def arrow(self, p, q, dashed=False, color=DARK):
        self.ax.annotate("", xy=q, xytext=p, arrowprops=dict(
            arrowstyle="-|>", color=color, lw=1.0, ls="--" if dashed else "-", shrinkA=0, shrinkB=0, mutation_scale=9))

    def line(self, pts, dashed=False, color=DARK, lw=1.0):
        self.ax.plot([a[0] for a in pts], [a[1] for a in pts], color=color, lw=lw, ls="--" if dashed else "-")

    def poly(self, pts, dashed=False, color=DARK):
        """Đường gấp khúc, mũi tên ở đoạn cuối."""
        if len(pts) > 2:
            self.line(pts[:-1], dashed, color)
        self.arrow(pts[-2], pts[-1], dashed, color)

    def save(self, name):
        self.fig.savefig(os.path.join(OUT, name), dpi=220, facecolor="white")
        plt.close(self.fig)
        print("saved", name)


def bottom(b):
    return (b[0] + b[2] / 2, b[1] + b[3])


def top(b):
    return (b[0] + b[2] / 2, b[1])


def right(b):
    return (b[0] + b[2], b[1] + b[3] / 2)


def left(b):
    return (b[0], b[1] + b[3] / 2)


def legend(f, x, y):
    items = [("llm", "có LLM stage"), ("code", "code tất định"), ("tool", "chạy EDA tool"), ("gate", "gate / quyết định")]
    for i, (k, t) in enumerate(items):
        xx = x + i * 24
        f.box(xx, y, 4, 2.6, "", k)
        f.text(xx + 5.2, y + 1.3, t, fs=7, ha="left")


# ---------------------------------------------------------------- 1. Kiến trúc
def fig_architecture():
    f = Fig(100, 114)
    f.title(1, 3, "Giao diện người dùng")
    c = [f.box(2, 6, 28, 9, "CLI (click)\nq3tui run · status · approve …"),
         f.box(36, 6, 28, 9, "TUI (Textual)\ndashboard · gate · câu hỏi"),
         f.box(70, 6, 28, 9, "Trợ lý chat (trong TUI)\nmột tool cho mỗi op")]
    f.box(2, 20, 96, 7, "core/ops.py — mọi thao tác của người dùng (template, review, answer, approve, change, reset, run, model, cost)", "bar", fs=7.4)
    for b in c:
        f.arrow(bottom(b), (b[0] + b[2] / 2, 20))
    f.box(2, 31, 96, 7, "core/events.py — event bus (CLI printer · TUI · .q3tui/runs/<id>/events.jsonl cùng đăng ký)", "bar", fs=7.4)
    f.arrow((50, 27), (50, 31))
    f.title(1, 42, "Pipeline engine")
    f.box(2, 44.5, 96, 12, "pipeline/engine.py — đồ thị step của flow · staleness theo content-hash · gate · vòng sửa lỗi (fix loop)\n"
          "câu hỏi & quyết định · pipeline.json (trạng thái, step_meta) · core/chain.py (q3tui auto) · core/loop.py", "code", fs=7.4)
    f.arrow((50, 38), (50, 44.5))
    f.title(1, 60, "Flows (dữ liệu) và step kinds")
    names = ["spec", "rtl", "dv", "sanity", "fpga", "asic", "project", "example"]
    for i, n in enumerate(names):
        f.box(2 + i * 12.1, 63, 11, 6, n, "llm", fs=8, bold=True)
    f.arrow((50, 56.5), (50, 63))
    f.text(50, 73, "mỗi step = các stage nối tiếp:  D (code tất định) · L (LLM stage) · T (chạy tool)", fs=7.4, italic=True)
    f.arrow((50, 75), (50, 79))
    b1 = f.box(2, 79, 30, 17, "LLM runtime\nllm/runtime.py: run_stage\nClaude Agent SDK query()\nMCP trong tiến trình (mcp__q3tui__*)\nhook PreToolUse · pydantic output", "llm", fs=7.2)
    b2 = f.box(35, 79, 30, 17, "Lớp HDL\nhdl/: filelist, pyslang\nparse RTL, danh sách module,\nrule check\n(chạy trong process Python)", "code", fs=7.2)
    b3 = f.box(68, 79, 30, 17, "Tools theo role\neda/tools.py + config/tools.json\nlint · synth · sim · cdc · …\nmẫu lệnh + log parser\nrole thiếu tool → N/A", "tool", fs=7.2)
    for b in (b1, b2, b3):
        f.arrow((b[0] + b[2] / 2, 76), (b[0] + b[2] / 2, 79))
    f.line([(17, 75), (83, 75)])
    f.box(2, 100, 30, 8, "Provider: claude · claude_api\nopenai · openai_api (gateway LiteLLM)", "plain", fs=7.2)
    f.box(35, 100, 30, 8, "Thư mục dự án: spec/ src/ schemas/\nreports/ build/ .q3tui/", "plain", fs=7.2)
    f.box(68, 100, 30, 8, "EDA tool của site (Linux):\nVCS · DC · VC Static · Vivado · Verible", "plain", fs=7.2)
    f.arrow(bottom(b1), (17, 100))
    f.arrow(bottom(b2), (50, 100))
    f.arrow(bottom(b3), (83, 100))
    legend(f, 2, 111)
    f.save("fig_01_architecture.png")


# ---------------------------------------------------------------- 2. Chuỗi flow chính
GATES = ["Gate 1 (parse): human\nGate 2 (config): auto", "lỗi lint / smoke\nquay về step rtl", "testplan: human;\nlỗi RTL → flow rtl",
         "setup, waivers: human\nfix loop → rtl", "timing report: human\nppa_optimize: human"]


def fig_chain():
    f = Fig(100, 62)
    labels = [("spec", "intent → spec\n→ REQ → config", "llm"),
              ("rtl", "RTL, format,\nstyle lint, smoke", "llm"),
              ("dv", "testplan → tb\n→ simulate", "llm"),
              ("sanity", "CDC / RDC,\nwaiver review", "llm"),
              ("fpga / asic", "PPA, synthesis,\nLEC", "tool")]
    bs = []
    for i, (n, d, k) in enumerate(labels):
        x = 2 + i * 19.6
        f.box(x, 5, 16.5, 5.5, n, k, fs=9.5, bold=True)
        f.box(x, 10.5, 16.5, 17, d + "\n\n" + GATES[i], "plain", fs=7.2)
        bs.append(x)
    for a, b in zip(bs[:-1], bs[1:]):
        f.arrow((a + 16.5, 13.5), (b, 13.5))
    f.text(50, 1.5, "Chuỗi flow của pipeline.chain (mặc định: spec → rtl → dv → sanity → fpga)", fs=8.2, bold=True, color=PURPLE)
    # đường quay lại (từ dv, sanity, fpga về rtl)
    f.line([(91.5, 27.5), (91.5, 33), (22, 33)], dashed=True, color=PURPLE)
    f.line([(71.9, 27.5), (71.9, 33)], dashed=True, color=PURPLE)
    f.line([(52.3, 27.5), (52.3, 33)], dashed=True, color=PURPLE)
    f.arrow((22, 33), (22, 27.5), dashed=True, color=PURPLE)
    f.text(50, 38.5, "Một flow làm RTL thay đổi (hash src/rtl/ trước và sau) → các flow kiểm tra đã pass với RTL cũ (dv, sanity, fpga)\nchạy lại theo thứ tự chuỗi, tối đa pipeline.chain_max_runs lần (mặc định 3)", fs=7.2, color=PURPLE, italic=True)
    f.box(2, 45, 96, 13, "q3tui auto / TUI /auto: chạy hết chuỗi không cần người — gate tự duyệt, câu hỏi nhận giá trị mặc định;\nflow không pass thì dừng và in bảng (flow, có đổi RTL không, chi phí).\nMỗi flow cũng chạy riêng được: q3tui --flow rtl run; nhiều flow chạy cùng lúc trong một thư mục dự án (mỗi flow một lock).", "bar", fs=7.4)
    f.save("fig_02_flow_chain.png")


# ---------------------------------------------------------------- 3. spec + rtl
def fig_spec_rtl():
    f = Fig(100, 74)
    f.title(1, 3, "Flow spec (mặc định)")
    sp = [("spec", "human", "llm"), ("parse", "human (Gate 1)", "llm"), ("config", "auto (Gate 2)", "code")]
    bx = [f.box(2 + i * 20, 6, 15, 8, n + "\n" + g, k, fs=7.4) for i, (n, g, k) in enumerate(sp)]
    for a, b in zip(bx[:-1], bx[1:]):
        f.arrow(right(a), left(b))
    f.text(66, 10, "spec/spec.md →\nschemas/structured_spec.json (REQ-NNN) →\nschemas/final_config.json", fs=7, ha="left", color=GREY)
    f.title(1, 21, "Flow rtl (dùng lại ba step trên, thêm sáu step)")
    row1 = [("spec", "human", "llm"), ("rules", "code + LLM", "llm"), ("parse", "human", "llm"), ("config", "auto", "code"), ("csr", "LLM + tool", "llm")]
    r1 = [f.box(2 + i * 19.6, 25, 16, 8, n + "\n" + g, k, fs=7.4) for i, (n, g, k) in enumerate(row1)]
    for a, b in zip(r1[:-1], r1[1:]):
        f.arrow(right(a), left(b))
    row2 = [("rtl", "LLM + tool", "llm"), ("format", "code", "code"), ("style_lint", "code + LLM", "llm"), ("smoke", "code + LLM", "llm")]
    r2 = [f.box(2 + i * 19.6, 43, 16, 8, n + "\n" + g, k, fs=7.4) for i, (n, g, k) in enumerate(row2)]
    for a, b in zip(r2[:-1], r2[1:]):
        f.arrow(right(a), left(b))
    f.poly([bottom(r1[4]), (bottom(r1[4])[0], 38), (10, 38), (10, 43)])
    # vòng sửa lỗi
    f.poly([(bottom(r2[2])[0], 51), (bottom(r2[2])[0], 56), (7, 56), (7, 51)], dashed=True, color=PURPLE)
    f.poly([(bottom(r2[3])[0], 51), (bottom(r2[3])[0], 60), (4.5, 60), (4.5, 51)], dashed=True, color=PURPLE)
    f.text(38, 54.2, "style_lint → change request [rtl:<module>]", fs=7, color=PURPLE, italic=True)
    f.text(38, 58.2, "smoke → change request [rtl:<module>]", fs=7, color=PURPLE, italic=True)
    f.box(2, 66, 96, 6.5, "rules: kiểm tra mâu thuẫn trước khi viết RTL → cờ Verible · csr: thanh ghi sinh bởi APB-CSR-Generator\nsmoke: testbench viết chỉ từ spec, requirements và configuration — không bao giờ từ RTL", "bar", fs=7.2)
    f.save("fig_03_spec_rtl.png")


# ---------------------------------------------------------------- 4. dv
def fig_dv():
    f = Fig(100, 70)
    f.title(1, 3, "Flow dv")
    row1 = [("spec", "human"), ("parse", "human"), ("config", "auto"), ("testplan", "human")]
    row2 = [("tb", "auto"), ("prepare", "auto"), ("simulate", "auto")]
    r1 = [f.box(2 + i * 24.5, 7, 20, 8, n + "\n" + g, "llm", fs=8) for i, (n, g) in enumerate(row1)]
    for a, b in zip(r1[:-1], r1[1:]):
        f.arrow(right(a), left(b))
    r2 = [f.box(2 + i * 24.5, 28, 20, 8, n + "\n" + g, "tool" if n == "prepare" else "llm", fs=8) for i, (n, g) in enumerate(row2)]
    for a, b in zip(r2[:-1], r2[1:]):
        f.arrow(right(a), left(b))
    f.poly([bottom(r1[3]), (bottom(r1[3])[0], 21), (12, 21), (12, 28)])
    tri = f.box(2, 46, 38, 9, "Triage test lỗi (flows/dv/triage.py)\nso với lịch sử: phiên bản nào đã đổi RTL?", "code", fs=7.4)
    f.line([bottom(r2[2]), (bottom(r2[2])[0], 42), (21, 42)])
    f.arrow((21, 42), (21, 46))
    f.box(48, 46, 24, 9, "Lỗi testbench\n→ sửa ở step tb", "llm", fs=7.4)
    f.box(75, 46, 23, 9, "Lỗi RTL → change request\ntới step rtl (flow rtl)", "llm", fs=7.2)
    f.arrow(right(tri), (48, 50.5))
    f.line([(21, 55), (21, 59), (86.5, 59)])
    f.arrow((86.5, 59), (86.5, 55))
    f.text(50, 63, "Hai loại testbench (option testbench của step tb): plain — IP bất kỳ, test plan có duyệt;\nuvm — IP kiểu AXI đã có VIP, verification contract.", fs=7.2, color=GREY)
    f.text(50, 68, "testbench không bao giờ thấy RTL (tới giai đoạn tích hợp cuối của backend UVM); RTL không thấy src/tb/.", fs=7.2, color=GREY)
    f.save("fig_04_dv_flow.png")


# ---------------------------------------------------------------- 5. sanity
def fig_sanity():
    f = Fig(100, 66)
    f.title(1, 3, "Flow sanity — phân tích CDC / RDC")
    sdc = f.box(2, 22, 11, 8, "sdc\ncode", "code", fs=8)
    st = f.box(17, 22, 14, 8, "setup\nLLM · human", "llm", fs=7.8)
    f.arrow(right(sdc), left(st))
    for k, y in (("cdc", 8), ("rdc", 36)):
        a = f.box(38, y, 13, 8, k + "\nVC Static", "tool", fs=8)
        b = f.box(57, y, 20, 8, k + "_waivers\nLLM · human", "llm", fs=7.8)
        c = f.box(82, y, 16, 8, k + "_check\ncode", "code", fs=8)
        f.arrow(right(a), left(b))
        f.arrow(right(b), left(c))
    f.line([right(st), (34.5, 26), (34.5, 12)])
    f.arrow((34.5, 12), (38, 12))
    f.line([(34.5, 26), (34.5, 40)])
    f.arrow((34.5, 40), (38, 40))
    f.text(50, 52, "Mỗi vi phạm được xếp vào: waiver · RTL fix · câu hỏi spec · yêu cầu SDC · câu hỏi cho người dùng", fs=7.4, color=GREY)
    f.box(2, 55, 96, 10, "q3tui --flow sanity loop:  phân tích + review → sanity_handoff → flow rtl sửa RTL → phân tích lại.\nDừng khi hết vi phạm mở (clean), khi vòng không tốt hơn vòng tốt nhất, hết --max-rounds hoặc --max-cost;\nRTL của vòng tốt nhất giữ trong .q3tui/loop/best_rtl/.", "bar", fs=7.2)
    f.save("fig_05_sanity_flow.png")


# ---------------------------------------------------------------- 6. fpga / asic
def fig_fpga_asic():
    f = Fig(100, 68)
    f.title(1, 3, "Flow fpga — ước lượng PPA trên một FPGA part")
    n1 = [("fpga_port", "LLM + code", "llm"), ("sdc", "code", "code"), ("fpga_synth", "tool", "tool"),
          ("timing_util\n_report", "human", "llm"), ("ppa_optimize", "human", "llm")]
    r1 = [f.box(2 + i * 19.6, 7, 16, 10, n + "\n" + g, k, fs=7.2) for i, (n, g, k) in enumerate(n1)]
    for a, b in zip(r1[:-1], r1[1:]):
        f.arrow(right(a), left(b))
    f.poly([(bottom(r1[3])[0], 17), (bottom(r1[3])[0], 22), (10, 22), (10, 17)], dashed=True, color=PURPLE)
    f.text(55, 25, "mọi vấn đề của synthesis → change request về fpga_port, rồi chạy lại port và synth", fs=7, color=PURPLE, italic=True)
    f.title(1, 32, "Flow asic — synthesis tới netlist standard-cell và kiểm tra tương đương")
    ap = f.box(2, 37, 24, 9, "asic_port\nLLM + code · human", "llm", fs=7.2)
    sd = f.box(2, 50, 24, 9, "sdc\ncode", "code", fs=7.2)
    sy = f.box(42, 43, 26, 9, "asic_synth\nDesign Compiler · human", "tool", fs=7.2)
    lc = f.box(76, 43, 22, 9, "asic_lec\nFormality · human", "tool", fs=7.2)
    f.line([right(ap), (34, 41.5), (34, 47.5)])
    f.line([right(sd), (34, 54.5), (34, 47.5)])
    f.arrow((34, 47.5), left(sy))
    f.arrow(right(sy), left(lc))
    f.text(50, 63.5, "RTL ↔ netlist: Formality · thiếu tool hoặc library → step fail (\"not run\"), không bao giờ pass", fs=7, color=GREY)
    f.save("fig_06_fpga_asic.png")


# ---------------------------------------------------------------- 7. update not rerun
def fig_update():
    f = Fig(100, 96)
    s0 = f.box(26, 2, 48, 8, "Đầu vào của step đổi: spec, REQ, answer,\nchange request, file người dùng sửa", "plain", fs=7.6)
    s1 = f.box(26, 15, 48, 8, "So với snapshot step_meta trong pipeline.json\n(diff bằng code: section / REQ / module / answer nào mới)", "code", fs=7.4)
    f.arrow(bottom(s0), top(s1))
    f.diamond(50, 35, 40, 12, "Có thay đổi\nliên quan không?")
    f.arrow(bottom(s1), (50, 29))
    f.box(2, 49, 38, 13, "Không: không gọi LLM\nctx.unchanged = True\nGiữ nguyên artifact và approval", "code", fs=7.4)
    f.line([(30, 35), (21, 35)])
    f.arrow((21, 35), (21, 49))
    f.text(25.5, 32.5, "không", fs=7, italic=True)
    f.box(50, 49, 48, 13, "Có: LLM nhận artifact hiện tại + đúng phần đã đổi,\ntrả về chỉ các phần thay đổi (patch)\nCode áp patch; phần còn lại giữ nguyên byte", "llm", fs=7.2)
    f.line([(70, 35), (74, 35)])
    f.arrow((74, 35), (74, 49))
    f.text(71.5, 32.5, "có", fs=7, italic=True)
    f.box(50, 67, 48, 9, "Thay đổi thật → mở lại review của step\n(các phần đổi được liệt kê trong log)", "gate", fs=7.2)
    f.arrow((74, 62), (74, 67))
    f.box(26, 84, 60, 8, "Ghi snapshot mới; step downstream thấy hash đổi\nvà tự cập nhật theo cùng cách", "code", fs=7.4)
    f.line([(21, 62), (21, 88)])
    f.arrow((21, 88), (26, 88))
    f.arrow((74, 76), (74, 84))
    f.save("fig_07_update_not_rerun.png")


# ---------------------------------------------------------------- 8. gate & câu hỏi
def fig_gate():
    f = Fig(100, 94)
    a = f.box(30, 2, 40, 7, "Step chạy xong (các stage D / L / T)", "plain", fs=8)
    b = f.box(26, 14, 48, 9, "Câu hỏi của step: mỗi câu có default_assumption\nvà 2–4 lựa chọn kèm tác động (area/speed/power/complexity)", "llm", fs=7.2)
    f.arrow(bottom(a), top(b))
    f.diamond(50, 36, 44, 13, "Chế độ gate\ncủa step?")
    f.arrow(bottom(b), (50, 29.5))
    f.box(2, 51, 22, 12, "human\ndừng chờ review:\napprove · answer ·\nedit · change request", "gate", fs=7)
    f.box(27, 51, 22, 12, "auto\ntự duyệt khi xong;\ncâu hỏi blocking\nvẫn dừng", "code", fs=7)
    f.box(52, 51, 22, 12, "auto_answer\nvô nhân: duyệt hết,\nmọi câu hỏi nhận\ngiá trị mặc định", "code", fs=7)
    f.box(77, 51, 21, 12, "none\nkhông có gate\n(blocking vẫn dừng)", "code", fs=7)
    f.line([(28, 36), (13, 36)])
    f.arrow((13, 36), (13, 51))
    f.line([(50, 42.5), (50, 46), (38, 46)])
    f.arrow((38, 46), (38, 51))
    f.line([(50, 46), (63, 46)])
    f.arrow((63, 46), (63, 51))
    f.line([(72, 36), (87.5, 36)])
    f.arrow((87.5, 36), (87.5, 51))
    f.box(2, 68, 96, 24, "", "bar")
    f.text(4, 71.5, "Câu hỏi đi về step sở hữu artifact (theo kind):", fs=7.8, ha="left", bold=True)
    rows = ["spec_gap — spec thiếu / mơ hồ / mâu thuẫn  →  step spec",
            "req_gap — thiếu hoặc sai requirement  →  gap_targets của flow (flow spec: parse)",
            "arch_gap — quyết định cấu hình sai  →  gap_targets của flow (flow spec: config)",
            "design_choice — step tự quyết  →  ở lại step đã hỏi"]
    for i, r in enumerate(rows):
        f.text(5, 75.5 + i * 3.3, r, fs=7.2, ha="left")
    f.text(5, 89, "Chỉ chỉ ngược về step trước, không bao giờ về step sau; trả lời = change request [decision] trên step chủ.", fs=7, ha="left", italic=True, color=GREY)
    f.save("fig_08_gate_questions.png")


# ---------------------------------------------------------------- 9. fix loop
def fig_fixloop():
    f = Fig(100, 70)
    r = f.box(2, 4, 28, 9, "Step kiểm tra\n(format · lint · smoke · simulate · check)", "tool", fs=7.2)
    f.diamond(42, 8.5, 18, 11, "Đạt?", fs=8)
    f.arrow(right(r), (33, 8.5))
    ok = f.box(72, 4, 26, 9, "Đi tiếp / gate review", "code", fs=7.6)
    f.arrow((51, 8.5), left(ok))
    f.text(61.5, 6.3, "đạt", fs=7, italic=True)
    tr = f.box(28, 25, 44, 10, "Triage: lỗi của ai? (LLM đọc kết quả tool và lịch sử)\n→ scoped change request  [rtl:<module>] …", "llm", fs=7.2)
    f.arrow((42, 14), (46, 25))
    f.text(37, 19.5, "không", fs=7, italic=True)
    own = f.box(28, 42, 44, 9, "Step chủ sở hữu cập nhật chỉ unit được nêu\n(patch, không viết lại cả step)", "llm", fs=7.2)
    f.arrow(bottom(tr), top(own))
    f.line([(28, 46.5), (8, 46.5)])
    f.arrow((8, 46.5), (8, 13))
    f.text(14, 30, "chạy lại\nstep kiểm tra", fs=7, color=PURPLE, italic=True)
    f.box(2, 57, 96, 11, "Dừng khi: hết pipeline.max_fix_iterations vòng (hoặc options.max_fix_rounds của step) · cùng một finding lặp lại\npipeline.escalate_after_repeats lần → thành câu hỏi cho người dùng · đạt bound thì step fail, không bao giờ \"pass\" phần còn lại.\nSửa thuộc flow khác (dv → RTL): hand_to_flow, chạy trong cùng một run.", "bar", fs=7)
    f.save("fig_09_fix_loop.png")


# ---------------------------------------------------------------- 10. LLM stage
def fig_llm_stage():
    f = Fig(100, 84)
    s = f.box(2, 4, 28, 14, "Step (code)\nStage(...): prompt,\nallow-list tool, output_model,\ncwd, add_dirs, deny_dirs", "code", fs=7.2)
    r = f.box(36, 4, 28, 14, "llm/runtime.run_stage\nmodel, effort, provider\nsession: fresh / flow / team\ncheckpoint, ngân sách token", "llm", fs=7.2)
    p = f.box(70, 4, 28, 14, "Claude Agent SDK\nquery(), permission_mode\n= dontAsk\n(provider quyết định đích)", "llm", fs=7.2)
    f.arrow(right(s), left(r))
    f.arrow(right(r), left(p))
    f.box(36, 28, 28, 12, "Hook PreToolUse\nchỉ cho phép Stage.cwd + add_dirs\nchặn deny_dirs và .q3tui/", "gate", fs=7)
    f.box(70, 28, 28, 12, "Tool được phép\nRead · Grep · Glob (+ Write/Edit)\nmcp__q3tui__* · Bash chỉ cho\nlệnh của một tool role", "tool", fs=7)
    f.arrow((84, 18), (84, 28))
    f.arrow((70, 34), (64, 34))
    o = f.box(36, 50, 28, 10, "Kết quả có cấu trúc\n(JSON theo pydantic schema)", "llm", fs=7.2)
    f.line([(84, 40), (84, 45), (50, 45)])
    f.arrow((50, 45), (50, 50))
    v = f.box(36, 66, 28, 10, "run_stage validate bằng pydantic;\nsai → hỏi lại trong cùng session", "code", fs=7.2)
    f.arrow(bottom(o), top(v))
    c = f.box(2, 66, 28, 10, "Code ghi file, chạy check\ntất định, sở hữu fix loop", "code", fs=7.2)
    f.arrow(left(v), right(c))
    lg = f.box(70, 66, 28, 10, "Ghi log: events.jsonl,\nstats.jsonl (chi phí / stage)", "plain", fs=7.2)
    f.arrow(right(v), left(lg))
    f.text(50, 81, "Mọi lời gọi LLM đi qua đúng một hàm: q3tui.llm.runtime.run_stage", fs=7.6, color=PURPLE, bold=True)
    f.save("fig_10_llm_stage.png")


# ---------------------------------------------------------------- 11. providers
def fig_providers():
    f = Fig(100, 64)
    r = f.box(2, 22, 22, 12, "run_stage\n+ Claude Agent SDK", "llm", fs=8)
    sw = f.box(30, 22, 18, 12, "llm.provider\n(provider.py)", "code", fs=8)
    f.arrow(right(r), left(sw))
    f.line([right(sw), (52, 28)])
    f.line([(52, 8), (52, 40)])
    for y, k in ((3, "claude: Anthropic, đăng nhập Claude Code"),
                 (14, "claude_api: Claude API hoặc endpoint cùng giao thức\n(llm.api_base) · ANTHROPIC_API_KEY")):
        f.box(56, y, 42, 9, k, "plain", fs=7.2)
        f.arrow((52, y + 4.5), (56, y + 4.5))
    f.box(56, 27, 42, 12, "Gateway (llm/gateway.py): proxy LiteLLM, 127.0.0.1\nvenv riêng ~/.q3tui/gateway/venv\nnhận request Anthropic → chuyển sang OpenAI", "tool", fs=7)
    f.arrow((52, 33), (56, 33))
    f.box(56, 44, 20, 9, "openai\nđăng nhập ChatGPT", "plain", fs=7.2)
    f.box(78, 44, 20, 9, "openai_api\nAPI / vLLM / Ollama", "plain", fs=7.2)
    f.arrow((66, 39), (66, 44))
    f.arrow((88, 39), (88, 44))
    f.box(2, 44, 46, 14, "Khóa API: ~/.q3tui/keys.env (mode 600, core/keys.py)\nq3tui keys set NAME — biến môi trường cùng tên thắng;\nkhông bao giờ ghi vào q3tui.yaml", "bar", fs=7)
    f.save("fig_11_providers.png")


# ---------------------------------------------------------------- 12. độc lập
def fig_independence():
    f = Fig(100, 58)
    f.box(30, 4, 40, 18, "spec · requirements (parse) · configuration\n\nschemas/structured_spec.json\nschemas/final_config.json", "plain", fs=7.6)
    f.box(2, 34, 30, 12, "RTL: src/rtl/\n(flow rtl: step rtl)", "llm", fs=8)
    f.box(68, 34, 30, 12, "Testbench: src/tb/\n(flow dv: tb · flow rtl: smoke)", "llm", fs=8)
    f.line([(38, 22), (38, 28), (17, 28)])
    f.arrow((17, 28), (17, 34))
    f.line([(62, 22), (62, 28), (83, 28)])
    f.arrow((83, 28), (83, 34))
    f.line([(50, 26), (50, 49)], dashed=True, color=RED, lw=1.8)
    f.text(50, 52, "hook PreToolUse + deny_dirs: RTL và testbench tách biệt", fs=7.8, color=RED, bold=True)
    f.text(2, 50, "RTL không thấy src/tb/ và SVA", fs=7.2, ha="left")
    f.text(98, 50, "testbench không thấy RTL", fs=7.2, ha="right")
    f.save("fig_12_independence.png")


if __name__ == "__main__":
    for fn in (fig_architecture, fig_chain, fig_spec_rtl, fig_dv, fig_sanity, fig_fpga_asic, fig_update,
               fig_gate, fig_fixloop, fig_llm_stage, fig_providers, fig_independence):
        fn()
