# ECO flow — Workflow → Step → Task

```
q3tui/flows/eco/                 workflow: FLOW.md, addon.py, panels.py, lib/ (dùng chung)
  eco_rtl/                       step: md/skill.md (front matter, mô tả), step.py (class Step: inputs / outputs, run = các task theo thứ tự)
    plan/                        task: task.py (TASK = (tên, mô tả), code) + prompt.md (khi task gọi LLM)
    decide/  edit/  …
```

- Mỗi task là một thư mục `<step>/<task>/`: `task.py` chứa code, `prompt.md` chứa prompt nếu task gọi LLM (đọc bằng `task_prompt(__file__)`).
- `task.py` không bao giờ import `step.py` của step (loader nạp `step.py` theo đường dẫn file).
- Mỗi task ghi lại việc nó làm trong lần chạy (`EcoStep.task` → `schemas/eco_tasks.json`: done / skipped / waiting / handed / failed); TUI hiện ở tab **Tasks** của step.
- Không có task `check_inputs`: engine đã gọi `missing_input()` trước khi chạy step, thiếu input thì step không chạy.

## eco_inputs

| Task | Làm gì |
|---|---|
| `inputs` | Chọn ORG RTL, ORG netlist và requirement (mặc định của asic flow hoặc đường dẫn bạn đưa). |
| `mode` | Xác định RTL là của project (project mode) hay từ ngoài vào (external mode). |
| `ref` | Lưu bản ORG vào `ref/<name>/` để so sánh và khôi phục về sau. |
| `record` | Ghi các lựa chọn trên vào `schemas/eco_inputs.json`. |

## eco_eq1

| Task | Làm gì |
|---|---|
| `decide` | Chọn dùng lại kết quả LEC của asic flow, chạy Formality, hay bỏ qua. |
| `formality` | Formality so ORG RTL với ORG netlist, để chắc chúng khớp trước khi sửa. |
| `advise` | Khi không khớp: AI giải thích lý do và cách xử lý (`eco/reports/eq1.md`). |

## eco_spec

| Task | Làm gì |
|---|---|
| `check_requirement` | Xem requirement có đổi không: đổi thì làm lại từ spec ORG, không đổi thì chỉ cập nhật theo change request. |
| `edit` | AI sửa spec theo requirement với thay đổi nhỏ nhất. |
| `concerns` | Mỗi lo ngại (concern) của AI thành một câu hỏi cho bạn: giữ thay đổi hay trả lời khác. |
| `diff` | Ghi `eco/spec.diff`: spec mới so với spec ORG. |

## eco_rtl

| Task | Làm gì |
|---|---|
| `check_requirement` | Xem requirement và ORG RTL có đổi không: đổi thì làm lại từ ORG, không đổi thì chỉ cập nhật theo change request. |
| `plan` | AI đọc RTL (không sửa) và tìm thay đổi nhỏ nhất đáp ứng requirement. |
| `decide` | Hỏi bạn khi có cách nhỏ hơn cách requirement yêu cầu (auto-answer chọn cách nhỏ hơn). |
| `edit` | AI sửa RTL theo plan đã chốt. |
| `concerns` | Mỗi lo ngại của AI thành một câu hỏi cho bạn. |
| `check` | Parse RTL mới và ghi `eco/rtl.diff`. |

## eco_verify

| Task | Làm gì |
|---|---|
| `ask` | Hỏi có chạy lại dv + Sanity trước khi sửa netlist không. |
| `dv` | Chạy dv flow: mọi test phải pass. |
| `sanity` | Chạy Sanity: không còn CDC / RDC nào mở; lỗi RTL quay về `eco_rtl`. |

## eco_patch

| Task | Làm gì |
|---|---|
| `edits` | AI viết lệnh netlist edit (Design Compiler) từ `eco/rtl.diff` và ORG netlist. |
| `check` | Tự thêm đường dẫn từ top cho tên instance / net thiếu nó (`tcl.qualify`), rồi từ chối lệnh không phải netlist edit hoặc không khớp netlist (trả lại AI một vòng). |

## eco_apply

| Task | Làm gì |
|---|---|
| `dc` | Design Compiler áp patch lên ORG netlist ra ECO NETLIST; lỗi quay về `eco_patch`. |

## eco_eq2

| Task | Làm gì |
|---|---|
| `formality` | Formality so RTL mới với ECO NETLIST. |
| `advise` | Khi không khớp: AI tìm nguyên nhân và step nên sửa (`eco_rtl` hay `eco_patch`). |
| `route` | Chuyển lỗi về đúng step đó, theo câu trả lời của bạn hoặc đề xuất (auto-answer). |

## eco_sta

| Task | Làm gì |
|---|---|
| `primetime` | PrimeTime kiểm setup / hold của ECO NETLIST với constraint ORG. |
| `fix` | Khi vi phạm setup: AI viết lệnh sửa timing, rồi quay về `eco_apply`. |
