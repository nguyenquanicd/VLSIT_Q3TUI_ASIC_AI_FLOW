"""Task input of the plain testbench stages (adapted from md/tb_generator.md; Vietnamese as in the original)."""

from __future__ import annotations

from pathlib import Path

from q3tui.flows import skill_sections
from q3tui.flows.dv.plain.plan import ROW_KINDS

# the stage system prompts are the named sections of md/prompts.md (this file only assembles the per-task input)
TEXT = skill_sections(Path(__file__).parent / "md" / "prompts.md")

PLAN_SYSTEM = TEXT["PLAN_SYSTEM"]

WRITE_SYSTEM = TEXT["WRITE_SYSTEM"]

REVIEW_SYSTEM = TEXT["REVIEW_SYSTEM"]

PLAN_REVIEW_SYSTEM = TEXT["PLAN_REVIEW_SYSTEM"]

QA_SYSTEM = TEXT["QA_SYSTEM"]

KEEP = "<!-- keep -->"  # (= q3tui.llm.runtime.KEEP, not imported: the Agent SDK loads lazily) a section a task must act on: never deduped

QA_DONE = ("\n## Q&A trước plan đã xong\nCác câu hỏi về spec đã được hỏi và trả lời (ở trên). Chỉ thêm câu hỏi khi một TC KHÔNG THỂ viết đúng nếu "
           "thiếu câu trả lời và nó chưa có ở trên; điều nhỏ hơn: dùng cách đọc hợp lý nhất và ghi giả định trong mô tả của TC.")


def qa_prompt(*, reqs: list[tuple[str, str, str]], params: dict[str, str], spec_files: list[str], top: str | None,
              asked: list[tuple[str, str]], skills: str = "") -> str:
    """The question sweep before the plan: the whole spec, every open point at once; a later round gets what was asked and answered."""
    parts = ["# Task: câu hỏi trước test plan" + (" (vòng tiếp: chỉ điều các câu trả lời mở ra)" if asked else ""),
             f"\nSpec: {_spec(spec_files)} — đọc toàn bộ." + (f"\nModule top (DUT): `{top}`" if top else ""),
             "\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs),
             "\n## Tham số đã chốt\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)")]
    if asked:
        parts.append("\n## Đã hỏi (câu hỏi → câu trả lời)\n" + "\n".join(f"- {q} → {a or '(chưa trả lời)'}" for q, a in asked))
    if skills:
        parts.append("\n" + skills)
    parts.append("\nTrả về `questions` (rỗng nếu spec đã đủ).")
    return "\n".join(parts)

def _spec(spec_files: list[str]) -> str:
    """The spec documents a stage reads, named as files: a Grep of their folder is blocked when it holds a folder the stage may not see
    (spec/ holds spec/ref/: every planning call of rv32iv lost a turn to it)."""
    if not spec_files:
        return "spec/"
    return ", ".join(f"`{f}`" for f in spec_files) + " (Grep / Read các file này, `path` = tên file; không Grep cả thư mục)"


DV_FLOW_FILE = Path(__file__).parents[1] / "FLOW.md"  # (the skills are found next to the dv flow whichever flow file runs its steps)


def quality_skills(project) -> tuple[str, list[Path]]:
    """The test-quality playbook (skill `tc-quality`; yours in config/skills/ wins) for the plan, write and review stages: (the prompt's index, the add_dirs)."""
    from q3tui.flows.rtl.lib import skills as skillmod

    found = skillmod.discover(project.config_dir, DV_FLOW_FILE, ["tc-quality"])
    return skillmod.index(found, project.root), skillmod.add_dirs(found)


def plan_prompt(*, reqs: list[tuple[str, str, str]], params: dict[str, str], spec_files: list[str], top: str | None,
                previous: list[dict] | None, changes: list[str], answers: dict[str, str], settled: str, feedback: list[str],
                uncovered: list[str], skills: str = "", inventory: list[dict] | None = None, missing_functions: dict[str, list[str]] | None = None,
                review: list[dict] | None = None, asked: list[str] | None = None, qa_done: bool = False,
                excluded: list[dict] | None = None, groups: list[dict] | None = None, missing_cells: dict[str, list[str]] | None = None,
                detail: set[str] | None = None) -> str:
    """`detail`: the tests of `previous` shown with their case tables (the others one line: a 248-test plan in full is ~250k tokens)."""
    parts = ["# Task: test plan" + (" (cập nhật)" if previous else "")]
    parts.append(f"\nSpec: {_spec(spec_files)}" + (f"\nModule top (DUT): `{top}`" if top else ""))
    parts.append("\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs))
    parts.append("\n## Tham số đã chốt (final_config.json)\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)"))
    if previous:
        parts.append("\n## Test plan hiện tại (giữ nguyên id; chỉ thay đổi phần bị ảnh hưởng)\n"
                     + "\n".join(_case_line(c, brief=detail is not None and c["tc_id"] not in detail) for c in previous))
        if groups:
            parts.append("\n## Group (giữ; một test mới ghi `group`; group mới / đổi trả về trong `groups`)\n" + _groups_block(groups))
        if excluded:
            parts.append("\n## Requirement đã loại khỏi mô phỏng (giữ nguyên; KHÔNG viết TC cho chúng, không cần ghi lại)\n"
                         + "\n".join(f"- {e['req_id']}: {e.get('reason', '')}" for e in excluded))
        if inventory:
            parts.append("\n## Function inventory hiện tại (giữ, bổ sung nếu thiếu)\n" + "\n".join(f"- {r['req_id']}: {', '.join(r['functions'])}" for r in inventory))
        if changes:
            parts.append("\n## Đầu vào đã thay đổi\n" + "\n".join(f"- {c}" for c in changes))
    if uncovered:
        parts.append("\n## " + KEEP + "Chưa có TC cover (thêm TC; nếu không thể kiểm tra bằng mô phỏng DUT thì đưa vào `excluded` kèm lý do — KHÔNG hỏi trong questions)\n"
                     + "\n".join(f"- {r}" for r in uncovered))
    if qa_done:
        parts.append(QA_DONE)
    if missing_functions:
        parts.append("\n## " + KEEP + "Chức năng trong inventory chưa có TC nào (không tính constrained_random) chạy — thêm hoặc mở rộng TC directed / combined / "
                     "fault_injection / stress, ghi đúng tên trong `functions`\n" + "\n".join(f"- {r}: {', '.join(fs)}" for r, fs in missing_functions.items()))
    if missing_cells:
        parts.append("\n## " + KEEP + "Ô ma trận chưa có test (thêm hàng / test, hoặc `not_applicable` của group kèm lý do)\n"
                     + "\n".join(f"- {g}: {', '.join(m)}" for g, m in missing_cells.items()))
    if review:
        parts.append("\n## " + KEEP + "Reviewer độc lập đã tìm thấy (mọi điểm `must` phải được xử lý — sửa TC, bỏ check / failure mode không thể fail, chuyển "
                     "requirement vào `excluded` với lý do, hoặc hỏi trong `questions` khi spec không nói; không được giữ nguyên; `should` nếu hợp lý)\n" + "\n".join(
            f"- [{f.get('severity', 'must')}] {f.get('tc_id') or 'plan'}: {f['problem']}" + (f" → {f['fix']}" if f.get("fix") else "") for f in review))
    if asked:
        parts.append("\n## " + KEEP + "Câu hỏi đang mở (đã hỏi người dùng: KHÔNG hỏi lại, kể cả với cách diễn đạt khác; chỉ thêm câu hỏi về điểm chưa có ở đây)\n"
                     + "\n".join(f"- {q}" for q in asked))
    if answers:
        parts.append("\n## Câu trả lời của người dùng\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items()))
    if settled:
        parts.append(settled)
    if feedback:
        parts.append("\n## " + KEEP + "Yêu cầu thay đổi\n" + "\n".join(f"- {f}" for f in feedback))
    if skills:
        parts.append("\n" + skills)
    if previous:  # (a patch: only what changes — the whole plan re-sent took 35–39k output tokens per update on rv32iv)
        parts.append("\nĐây là CẬP NHẬT: chỉ trả về phần thay đổi. `test_cases` = TC mới (tc_id \"\") và TC sửa (giữ tc_id, ghi cả hàng như nó phải là); "
                     "KHÔNG lặp lại TC không đổi — code giữ chúng. `removed` = TC bỏ (tc_id, lý do), thường rỗng. `inventory` = chỉ requirement có danh "
                     "sách chức năng đổi (cả danh sách mới). `excluded` = chỉ requirement MỚI loại. `questions`. Không có gì cần đổi thì mọi danh sách rỗng.")
    else:
        parts.append("\nTrả về `inventory` (đầy đủ), danh sách đầy đủ `test_cases` (mỗi TC có `failure_modes`, `observe`, `test_type` và "
                     "`functions`), `excluded` và `questions`.")
    return "\n".join(parts)


def _groups_block(groups: list[dict]) -> str:
    out = []
    for g in groups:
        bits = [f"REQ {', '.join(g['req_ids']) or '–'}"]
        for k, label in (("controls", "controls"), ("live_settings", "live settings"), ("random_domains", "random"), ("shares", "shares")):
            if g.get(k):
                bits.append(f"{label}: {', '.join(g[k])}")
        out.append(f"- `{g['name']}` — {g.get('title', '')} ({'; '.join(bits)})"
                   + "".join(f"\n  - n/a {n['function'] or '(group)'}: {n['kind']} — {n['reason']}" for n in g.get("not_applicable") or []))
    return "\n".join(out)


def _case_line(c: dict, brief: bool = False) -> str:
    """A test of the plan with its case table and random part (the planner's and the reviewer's view); `brief`: its line only (rv32iv: 248
    tests in full are ~600k characters, their lines ~70k)."""
    head = (f"- {c['tc_id']} {c['name']} [{c.get('test_type') or 'directed'}]" + (f" group {c['group']}" if c.get("group") else "")
            + (f" + {', '.join(c['with_groups'])}" if c.get("with_groups") else "") + f" → {', '.join(c['req_ids'])}: {c.get('description', '')}")
    if brief:
        return head + (f" ({len(c['rows'])} case(s))" if c.get("rows") else "") + (f" + random {c['random']['domain']}" if c.get("random") else "")
    rows = "".join(f"\n  - {r['id']} {r['function']} / {r['kind']}: {r.get('stimulus', '')} ⇒ {r.get('expect', '')}" for r in c.get("rows") or [])
    rnd = c.get("random")
    rnd_s = f"\n  - random: {rnd['domain']} × {rnd.get('count', 100)}, oracle: {rnd.get('oracle', '')}" if rnd else ""
    return (head + (f"\n  - functions: {', '.join(c['functions'])}" if c.get("functions") and not c.get("rows") else "") + rows + rnd_s
            + "".join(f"\n  - FM{k}: {f}" for k, f in enumerate(c.get("failure_modes") or [], 1)))


def matrix_prompt(*, reqs: list[tuple[str, str, str]], params: dict[str, str], spec_files: list[str], top: str | None, answers: dict[str, str],
                  settled: str, feedback: list[str], skills: str = "", qa_done: bool = False, ungrouped: list[str] | None = None,
                  groups: list[dict] | None = None, inventory: list[dict] | None = None, asked: list[str] | None = None) -> str:
    """Stage 1 of a new plan: the verification matrix (inventory + groups + excluded), no test case yet."""
    parts = ["# Task: test plan — bước 1: ma trận kiểm chứng (CHƯA viết test case)",
             f"\nSpec: {_spec(spec_files)} — đọc toàn bộ." + (f"\nModule top (DUT): `{top}`" if top else ""),
             "\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs),
             "\n## Tham số đã chốt (final_config.json)\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)")]
    if ungrouped:
        parts.append("\n## " + KEEP + "Requirement chưa thuộc group nào (thêm vào một group — group mới hoặc group có sẵn, trả lại cả group — hoặc "
                     "đưa vào `excluded` kèm lý do)\n" + "\n".join(f"- {r}" for r in ungrouped))
        parts.append("\n## Group hiện có\n" + _groups_block(groups or []))
        if inventory:
            parts.append("\n## Function inventory hiện có (chỉ trả lại requirement mới / đổi)\n"
                         + "\n".join(f"- {r['req_id']}: {', '.join(r['functions'])}" for r in inventory))
    if qa_done:
        parts.append(QA_DONE)
    if asked:
        parts.append("\n## " + KEEP + "Câu hỏi đang mở (KHÔNG hỏi lại)\n" + "\n".join(f"- {q}" for q in asked))
    if answers:
        parts.append("\n## Câu trả lời của người dùng\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items()))
    if settled:
        parts.append(settled)
    if feedback:
        parts.append("\n## " + KEEP + "Yêu cầu thay đổi\n" + "\n".join(f"- {f}" for f in feedback))
    if skills:
        parts.append("\n" + skills)
    parts.append("\nGroup nhỏ: khoảng 5 requirement và 100 ô ma trận trở xuống (mỗi chức năng 3 ô normal / boundary / error, cộng các ô "
                 "của group); group lớn hơn thì tách theo chức năng hoặc tài nguyên — test của một group được lập trong một lần trả lời.")
    parts.append("\nTrả về `inventory` (mọi requirement sẽ kiểm), `groups` (mỗi requirement đúng một group; với mỗi group: `controls`, "
                 "`live_settings`, `random_domains`, `shares`, và `not_applicable` cho ô ma trận chắc chắn không cần, kèm lý do từ spec), "
                 "`excluded` và `questions`. KHÔNG trả về test case: chúng được lập ở bước 2, từng group một.")
    return "\n".join(parts)


def group_plan_prompt(*, group: dict, reqs: list[tuple[str, str, str, str]], params: dict[str, str], spec_files: list[str], answers: dict[str, str],
                      settled: str, feedback: list[str], skills: str, groups: list[dict], inventory: list[dict], cases: list[dict],
                      missing: list[str] | None = None, asked: list[str] | None = None, part: int = 0) -> str:
    """Stage 2: the tests of one group (its requirements, its functions, its matrix cells); a gap round: only what code found missing
    (`part`: one piece of a long list; other calls of the same group take the rest at the same time)."""
    mine = {r for r in group["req_ids"]}
    parts = [f"# Task: test plan — bước 2: test của group `{group['name']}`" + (" (bổ sung phần còn thiếu)" if missing else ""),
             f"\n{group.get('title', '')}",
             f"\nSpec: {_spec(spec_files)} — đọc các mục của requirement dưới đây (Grep theo tên / mục), không cần đọc lại toàn bộ.",
             "\n## Requirement của group\n" + "\n".join(f"- {rid} [{cat}]: {text}" + (f" (spec: {sec})" if sec else "") for rid, cat, text, sec in reqs),
             "\n## Chức năng (inventory) — mỗi chức năng cần case normal, boundary, error (hoặc n/a kèm lý do)\n"
             + ("\n".join(f"- {r['req_id']}: {', '.join(r['functions'])}" for r in inventory if r["req_id"] in mine) or "(trống)"),
             "\n## Group này\n" + _groups_block([group]),
             "\nÔ của group: `reset` (reset giữa chừng một hoạt động của group), `stress`; `idle` cho mỗi control; `live_change` cho mỗi live "
             "setting; một test có phần `random` cho mỗi random domain; `interaction` với mỗi group chung tài nguyên (`shares`) — test đó ghi group kia "
             "trong `with_groups`.",
             "\n`kind` của một hàng là một trong: " + ", ".join(ROW_KINDS) + ". Kích thích ngẫu nhiên KHÔNG phải một hàng: nó là phần `random` "
             "của test. `req_ids`: chỉ id trong danh sách requirement của task này (của group này, hoặc của group khác ở dưới); nhãn viết trong "
             "văn bản spec (mã mục, mã requirement riêng của spec) không phải id.",
             "\n## Các group khác (chỉ để biết; KHÔNG lập test cho chúng)\n" + _groups_block([g for g in groups if g["name"] != group["name"]]),
             "\n## Tham số đã chốt\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)")]
    if cases:
        parts.append("\n## Test hiện có của group (giữ id; chỉ trả về test mới / sửa)\n" + "\n".join(_case_line(c) for c in cases))
    if missing:
        parts.append("\n## " + KEEP + "Code thấy còn thiếu (thêm hàng vào test có sẵn cùng setup, hoặc test mới; hoặc `not_applicable` kèm lý do từ spec)\n"
                     + "\n".join(f"- {m}" for m in missing))
        if part:
            parts.append("Đây là một phần của danh sách còn thiếu; các phần khác được lập song song. Viết test MỚI cho các ô trên; chỉ sửa test "
                         "có sẵn khi không thể khác (các phần khác cũng có thể sửa nó).")
    if asked:
        parts.append("\n## " + KEEP + "Câu hỏi đang mở (KHÔNG hỏi lại)\n" + "\n".join(f"- {q}" for q in asked))
    if answers:
        parts.append("\n## Câu trả lời của người dùng\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items()))
    if settled:
        parts.append(settled)
    if feedback:
        parts.append("\n## " + KEEP + "Yêu cầu thay đổi\n" + "\n".join(f"- {f}" for f in feedback))
    if skills:
        parts.append("\n" + skills)
    parts.append(f"\nTrả về `test_cases` của group (mỗi test: `group` = `{group['name']}`, `rows`, `random` nếu có, `failure_modes`, `observe`, "
                 "`test_type`), `not_applicable`, `excluded` (thường rỗng) và `questions`.")
    return "\n".join(parts)


def plan_review_prompt(*, reqs: list[tuple[str, str, str]], spec_files: list[str], inventory: list[dict], cases: list[dict],
                       excluded: list[dict], skills: str = "", asked: list[str] | None = None, qa_done: bool = False,
                       changed: set[str] | None = None, groups: list[dict] | None = None, whole: bool | None = None,
                       part: tuple[int, int] | None = None) -> str:
    """The plan reviewer's task: the plan as data. `changed`: the test cases this reviewer reads in full (the rest is listed one line each);
    `whole`: they are a new plan (all of it, maybe split: `part` = (j, of n) — other reviewers read the rest), else an update's changed tests
    (the rest was reviewed before). Only the groups / inventory of the tests reviewed are shown in full."""
    whole = changed is None if whole is None else whole
    mine = {c["tc_id"] for c in cases} if changed is None else changed
    rev = [c for c in cases if c["tc_id"] in mine]
    gnames = {c.get("group") for c in rev}  # (the groups whose tests it reads; one a test runs with is listed by name)
    greqs = {r for g in groups or [] if g["name"] in gnames for r in g["req_ids"]} | {r for c in rev for r in c["req_ids"]}
    parts = ["# Task: review test plan (chỉ đọc)" + ("" if whole and not part else f" — phần {part[0]}/{part[1]}" if whole else
                                                    " — CHỈ các TC vừa thay đổi"),
             f"\nSpec: {_spec(spec_files)} — đọc spec, đây là chuẩn để so.",
             "\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs),
             "\n## Function inventory (của requirement các TC được review)\n"
             + ("\n".join(f"- {r['req_id']}: {', '.join(r['functions'])}" for r in inventory if r["req_id"] in greqs) or "(trống)"),
             *(["\n## Group (kiểm cả các ô `n/a`: lý do có đúng spec không; controls / live settings / random domains / shares có bị bỏ sót không)\n"
                + _groups_block([g for g in groups if g["name"] in gnames])
                + "".join(f"\n- `{g['name']}` — {g.get('title', '')} (review riêng)" for g in groups if g["name"] not in gnames)] if groups else []),
             "\n## Test case"]
    if not whole:
        parts.append("Đây là bản CẬP NHẬT của một plan đã được review: chỉ review các TC dưới đây (vừa thêm / sửa). Các TC khác chỉ liệt kê tên để "
                     "bạn biết plan đã có gì; KHÔNG báo finding về chúng.")
    elif part:
        parts.append(f"Plan được chia cho {part[1]} reviewer theo group: review các TC dưới đây (đầy đủ); các TC khác chỉ liệt kê tên để bạn "
                     "biết plan đã có gì — reviewer khác đọc chúng; KHÔNG báo finding về chúng.")
    for c in rev:
        parts.append(_case_line(c) + f"\n  - observe: {c.get('observe') or '–'}")
    if len(rev) < len(cases):
        parts.append("\n## Các TC khác" + (" (đã review, không đổi)" if not whole else "") + "\n"
                     + "\n".join(f"- {c['tc_id']} {c['name']}" + (f" [{c['group']}]" if c.get("group") else "") + f" → {', '.join(c['req_ids'])}"
                                 for c in cases if c["tc_id"] not in mine))
    if excluded and whole:
        parts.append("\n## Excluded\n" + "\n".join(f"- {e['req_id']}: {e.get('reason', '')}" for e in excluded))
    if asked:
        parts.append("\n## " + KEEP + "Câu hỏi đang mở (đã hỏi người dùng: KHÔNG hỏi lại, kể cả với cách diễn đạt khác; chỉ thêm câu hỏi về điểm chưa có ở đây)\n"
                     + "\n".join(f"- {q}" for q in asked))
    if qa_done:
        parts.append("\n(Q&A về spec đã xong: chỉ hỏi trong `questions` khi một finding `must` phụ thuộc vào câu trả lời và nó chưa được hỏi.)")
    if skills:
        parts.append("\n" + skills)
    parts.append("\nTrả về `findings` (rỗng nếu plan tốt) và `questions`.")
    return "\n".join(parts)


def top_prompt(*, path: str, top: str | None, params: dict[str, str], spec_files: list[str], answers: dict[str, str],
               settled: str, feedback: list[str], problems: str, existing: bool, cases: list[dict], skills: str = "") -> str:
    parts = [f"# Task: viết testbench top → `{path}`", f"\nDUT: module `{top or '(xem spec)'}`; interface (port, clock, reset, giao thức) lấy từ spec: "
             f"{_spec(spec_files)}.",
             "\n## Tham số (instantiate DUT với các giá trị này)\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)"),
             "\n## Test case sẽ chạy (mỗi cái là một task `tc_<nnn>_<name>()` trong file riêng, do người khác viết; dùng tên tín hiệu/task của bạn)\n"
             + "\n".join(f"- tc_{int(c['tc_id'].split('-')[-1]):03d}_{c['name']}: {c.get('description', '')}" for c in cases),
             "\nChuẩn bị trong tb_top các tín hiệu và task trợ giúp cần cho các TC đó (ví dụ: reset_dut(), wait_cycles(n), bus read/write task) "
             "và GHI CHÚ ngắn đầu mỗi task trợ giúp (tên, tham số, hành vi) để người viết TC dùng.",
             "\nMonitor / checker luôn bật trong tb_top: mỗi bộ đếm vi phạm mà monitor giữ phải nằm trong MỘT task kiểm tra chung (ví dụ `mon_check_all()`) "
             "mà mọi TC gọi ở cuối — một bộ đếm không ai kiểm là checker chết. Task chờ (đợi halt, đợi done…) có timeout và báo lại là đã hết giờ. "
             "Kiểm tra chỉ trên giá trị DUT tạo ra, so sánh bằng `===` / `!==`."]
    if answers:
        parts.append("\nCâu trả lời của người dùng:\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items()))
    if settled:
        parts.append(settled)
    if feedback:
        parts.append("\nYêu cầu thay đổi:\n" + "\n".join(f"- {f}" for f in feedback))
    if skills:
        parts.append("\n" + skills)
    if existing:
        parts.append(f"\n`{path}` đã tồn tại: đọc rồi chỉ sửa phần cần sửa.")
    if problems:
        parts.append("\nVấn đề Q3TUI còn thấy (sửa hết):\n" + problems)
    return "\n".join(parts)


def group_prompt(*, cases: list[dict], paths: dict[str, str], reqs: dict[str, str], params: dict[str, str], spec_files: list[str],
                 top_path: str, answers: dict[str, str], settled: str, feedback: list[str], problems: str,
                 existing: set[str], skills: str = "", top_api: str = "") -> str:
    parts = ["# Task: viết các test case sau (mỗi TC một file, chỉ ghi các file này)"]
    if top_api:  # (first: the same for every group of the run, so the prompt cache shares it)
        parts.append("\n" + top_api)
    for c in cases:
        parts.append(f"\n### {c['tc_id']} {c['name']} → `{paths[c['tc_id']]}`" + (" (đã tồn tại: đọc rồi sửa)" if c["tc_id"] in existing else "")
                     + f"\n{c.get('description', '')}\nREQ: " + "; ".join(f"{r}: {reqs.get(r, '')}" for r in c["req_ids"])
                     + (f"\nQuan sát qua: {c['observe']}" if c.get("observe") else "")
                     + _fm_block(c))
    parts.append("\n## Tham số đã chốt\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)"))
    parts.append((f"\nTask của TC được include vào bên trong module tb_top (`{top_path}`; tóm tắt ở trên). " if top_api else
                  f"\nĐọc `{top_path}` để biết tín hiệu và task trợ giúp có sẵn trong tb_top (task TC được include vào bên trong module đó). ")
                 + f"Spec: {_spec(spec_files)}.")
    if answers:
        parts.append("\nCâu trả lời của người dùng:\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items()))
    if settled:
        parts.append(settled)
    if feedback:
        parts.append("\nYêu cầu thay đổi:\n" + "\n".join(f"- {f}" for f in feedback))
    if skills:
        parts.append("\n" + skills)
    if problems:
        parts.append("\nVấn đề Q3TUI còn thấy (kết quả công cụ là sự thật; sửa nguyên nhân):\n" + problems)
    return "\n".join(parts)


def _fm_block(c: dict) -> str:
    head = f"\nLoại test: {c.get('test_type') or 'directed'}" + (f"; chức năng: {', '.join(c['functions'])}" if c.get("functions") else "")
    if c.get("rows"):
        head += ("\nBảng case (mỗi hàng dưới `` `TC_CASE(\"<id>\") ``):\n"
                 + "\n".join(f"- {r['id']} {r['function']} / {r['kind']}: {r.get('stimulus', '')} ⇒ {r.get('expect', '')}" for r in c["rows"]))
    if c.get("random"):
        r = c["random"]
        head += f"\nPhần random: {r['domain']}, {r.get('count', 100)} case mặc định (`tc_rand_n`), oracle: {r.get('oracle', '')}"
    return head + _fms(c)


def _fms(c: dict) -> str:
    fms = c.get("failure_modes") or []
    if not fms:
        return "\nFailure mode: (plan không ghi) — tự xác định lỗi DUT mà TC này phải bắt, và đánh dấu check bắt nó bằng `// FM<k>:`."
    return ("\nFailure mode (mỗi cái một check bắt được nó, đánh dấu `// FM<k>:` ngay trên check):\n"
            + "\n".join(f"- FM{k}: {f}" for k, f in enumerate(fms, 1)))


def review_prompt(*, cases: list[dict], paths: dict[str, str], reqs: dict[str, str], spec_files: list[str], top_path: str, skills: str,
                  top_api: str = "") -> str:
    """The reviewer's task: the test cases just written, their plan rows (failure modes) and where to read them."""
    parts = ["# Task: review chất lượng các test case sau (chỉ đọc, không sửa)"]
    if top_api:
        parts.append("\n" + top_api)
    for c in cases:
        parts.append(f"\n### {c['tc_id']} {c['name']} → `{paths[c['tc_id']]}`\n{c.get('description', '')}\nREQ: "
                     + "; ".join(f"{r}: {reqs.get(r, '')}" for r in c["req_ids"])
                     + (f"\nQuan sát qua: {c['observe']}" if c.get("observe") else "") + _fm_block(c))
    parts.append((f"\ntb_top: tóm tắt ở trên; đọc thân task / monitor trong `{top_path}` mà TC dựa vào (offset / limit). Spec: " if top_api else
                  f"\nĐọc `{top_path}` (task, monitor và check chung mà TC dùng) và spec: ") + f"{_spec(spec_files)}.")
    if skills:
        parts.append("\n" + skills)
    parts.append("\nTrả về `findings` (rỗng nếu không có vấn đề) và `questions`.")
    return "\n".join(parts)


def review_fix_problems(findings: list[dict]) -> str:
    """The reviewer's must-findings as the problems of a fix session."""
    return "\n".join(f"- {f['tc_id']} [{f.get('rule') or 'quality'}] {f['problem']}" + (f" → sửa: {f['fix']}" if f.get("fix") else "") for f in findings)


def fix_prompt(*, label: str, problems: str, files: dict[str, str]) -> str:
    """A fresh small session: the problems and the current files."""
    body = "\n\n".join(f"`{p}`:\n```systemverilog\n{t}\n```" for p, t in files.items())
    return (f"# Task: sửa testbench ({label})\nTrình biên dịch/Q3TUI báo các lỗi sau (sự thật, sửa nguyên nhân):\n{problems}\n\n"
            f"Nội dung hiện tại:\n{body}\n\nSửa bằng Edit/Write rồi trả về tóm tắt.")


def top_change_prompt(*, path: str, requests: list[str], text: str) -> str:
    """A small session for change requests on tb_top only (`[tb:top] …`): the requests and the current file. The test cases are rewritten only when
    a task, macro or signal they use changes its declaration, so the session keeps those unless a request needs them changed."""
    return (f"# Task: sửa `{path}` theo yêu cầu thay đổi (chỉ file này)\n\nYêu cầu thay đổi:\n" + "\n".join(f"- {r}" for r in requests)
            + "\n\nCác test case (tests/*.sv, được include vào bên trong tb_top) dùng task, function, macro và tín hiệu của tb_top: giữ nguyên tên và "
              "khai báo (tham số) của chúng, trừ khi yêu cầu bắt buộc phải đổi — đổi thì các test case dùng chúng sẽ được viết lại. Chỉ sửa phần cần sửa.\n\n"
            + f"Nội dung hiện tại:\n```systemverilog\n{text}\n```\n\nSửa bằng Edit rồi trả về tóm tắt.")
