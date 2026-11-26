"""Task input of the plain testbench stages (adapted from md/tb_generator.md; Vietnamese as in the original)."""

from __future__ import annotations

from pathlib import Path

from q3tui.flows import skill_sections

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
             f"\nSpec: {', '.join(spec_files) or 'spec/'} — đọc toàn bộ." + (f"\nModule top (DUT): `{top}`" if top else ""),
             "\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs),
             "\n## Tham số đã chốt\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)")]
    if asked:
        parts.append("\n## Đã hỏi (câu hỏi → câu trả lời)\n" + "\n".join(f"- {q} → {a or '(chưa trả lời)'}" for q, a in asked))
    if skills:
        parts.append("\n" + skills)
    parts.append("\nTrả về `questions` (rỗng nếu spec đã đủ).")
    return "\n".join(parts)

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
                excluded: list[dict] | None = None) -> str:
    parts = ["# Task: test plan" + (" (cập nhật)" if previous else "")]
    parts.append(f"\nSpec: {', '.join(spec_files) or 'spec/'}" + (f"\nModule top (DUT): `{top}`" if top else ""))
    parts.append("\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs))
    parts.append("\n## Tham số đã chốt (final_config.json)\n" + ("\n".join(f"- {k} = {v}" for k, v in params.items()) or "(không có)"))
    if previous:
        parts.append("\n## Test plan hiện tại (giữ nguyên id; chỉ thay đổi phần bị ảnh hưởng)\n"
                     + "\n".join(f"- {c['tc_id']} {c['name']} [{c.get('test_type') or 'directed'}] → {', '.join(c['req_ids'])}: {c.get('description', '')}"
                                 + (f"\n  - functions: {', '.join(c['functions'])}" if c.get("functions") else "")
                                 + "".join(f"\n  - FM{k}: {f}" for k, f in enumerate(c.get("failure_modes") or [], 1)) for c in previous))
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


def plan_review_prompt(*, reqs: list[tuple[str, str, str]], spec_files: list[str], plan_path: str, inventory: list[dict], cases: list[dict],
                       excluded: list[dict], skills: str = "", asked: list[str] | None = None, qa_done: bool = False,
                       changed: set[str] | None = None) -> str:
    """The plan reviewer's task: the plan as data (it is also in `plan_path`). `changed`: an update — only those test cases are reviewed (the rest
    was reviewed before and is listed by name only)."""
    parts = ["# Task: review test plan (chỉ đọc)" + (" — CHỈ các TC vừa thay đổi" if changed is not None else ""),
             f"\nSpec: {', '.join(spec_files) or 'spec/'} — đọc spec, đây là chuẩn để so.",
             "\n## Requirement\n" + "\n".join(f"- {rid} [{cat}]: {text}" for rid, cat, text in reqs),
             "\n## Function inventory\n" + ("\n".join(f"- {r['req_id']}: {', '.join(r['functions'])}" for r in inventory) or "(trống)"),
             "\n## Test case"]
    if changed is not None:
        parts.append("Đây là bản CẬP NHẬT của một plan đã được review: chỉ review các TC dưới đây (vừa thêm / sửa). Các TC khác chỉ liệt kê tên để "
                     "bạn biết plan đã có gì; KHÔNG báo finding về chúng.")
    for c in cases:
        if changed is not None and c["tc_id"] not in changed:
            continue
        parts.append(f"- {c['tc_id']} {c['name']} [{c.get('test_type') or 'directed'}] → {', '.join(c['req_ids'])}: {c.get('description', '')}"
                     + f"\n  functions: {', '.join(c.get('functions') or []) or '–'}; observe: {c.get('observe') or '–'}"
                     + "".join(f"\n  FM{k}: {f}" for k, f in enumerate(c.get("failure_modes") or [], 1)))
    if changed is not None:
        parts.append("\n## Các TC khác (đã review, không đổi)\n" + "\n".join(f"- {c['tc_id']} {c['name']} → {', '.join(c['req_ids'])}"
                                                                          for c in cases if c["tc_id"] not in changed))
    if excluded and changed is None:
        parts.append("\n## Excluded\n" + "\n".join(f"- {e['req_id']}: {e.get('reason', '')}" for e in excluded))
    if asked:
        parts.append("\n## " + KEEP + "Câu hỏi đang mở (đã hỏi người dùng: KHÔNG hỏi lại, kể cả với cách diễn đạt khác; chỉ thêm câu hỏi về điểm chưa có ở đây)\n"
                     + "\n".join(f"- {q}" for q in asked))
    if qa_done:
        parts.append("\n(Q&A về spec đã xong: chỉ hỏi trong `questions` khi một finding `must` phụ thuộc vào câu trả lời và nó chưa được hỏi.)")
    parts.append(f"\n(Bản đầy đủ: `{plan_path}`.)")
    if skills:
        parts.append("\n" + skills)
    parts.append("\nTrả về `findings` (rỗng nếu plan tốt) và `questions`.")
    return "\n".join(parts)


def top_prompt(*, path: str, top: str | None, params: dict[str, str], spec_files: list[str], answers: dict[str, str],
               settled: str, feedback: list[str], problems: str, existing: bool, cases: list[dict], skills: str = "") -> str:
    parts = [f"# Task: viết testbench top → `{path}`", f"\nDUT: module `{top or '(xem spec)'}`; interface (port, clock, reset, giao thức) lấy từ spec: "
             f"{', '.join(spec_files) or 'spec/'}.",
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
                 + f"Spec: {', '.join(spec_files) or 'spec/'}.")
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
                  f"\nĐọc `{top_path}` (task, monitor và check chung mà TC dùng) và spec: ") + f"{', '.join(spec_files) or 'spec/'}.")
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
