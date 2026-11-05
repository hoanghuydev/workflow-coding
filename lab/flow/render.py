"""Markdown views rendered by the supervisor from validated JSON."""
from .contracts import BLOCKING, decisions


def bullets(items, empty="Không có."):
    return [f"- {item}" for item in items] or [f"- {empty}"]


def brief_lines(brief, heading="## Tóm tắt dễ đọc"):
    """The one-screen layer for people who will not read the whole document. Older documents have none."""
    if not brief:
        return []
    lines = [heading, ""]
    for title, key, numbered in (("Thay đổi người dùng sẽ thấy", "what_changes", False),
                                 ("Luồng chính sau khi làm", "main_flow", True),
                                 ("Không làm trong lần này", "not_doing", False),
                                 ("Điều có thể còn trục trặc", "risks", False)):
        items = brief.get(key) or []
        if items:
            lines += [f"**{title}:**", "", *([f"{n}. {i}" for n, i in enumerate(items, 1)] if numbered
                                             else [f"- {i}" for i in items]), ""]
    return lines


def assumption_lines(items, heading="## AI đã tự quyết (bạn có thể đổi)"):
    if not items:
        return []
    return [heading, "", *[f"- **{a['question']}** → {a['choice']}. {a['reason']}" for a in items], ""]


def prd_md(prd, round_):
    lines = [f"# PRD: {prd['title']}", "", f"Bản nháp vòng {round_}. Do AI soạn; xem cổng duyệt để biết trạng thái.", "",
             *brief_lines(prd.get("brief")), *assumption_lines(prd.get("assumptions")),
             "## Chi tiết", "", prd["summary"], "", "## Vấn đề", "", prd["problem"], "", "## Mục tiêu", "",
             *bullets(prd["goals"]), "",
             "## Ngoài phạm vi", "", *bullets(prd["non_goals"]), "", "## Người dùng", "", *bullets(prd["users"]), "",
             "## Yêu cầu", "", "| ID | Ưu tiên | Yêu cầu |", "| --- | --- | --- |"]
    lines += [f"| {r['id']} | {r['priority']} | {r['text']} |" for r in prd["requirements"]]
    lines += ["", "## Acceptance criteria", ""]
    for ac in prd["acceptance_criteria"]:
        lines += [f"### {ac['id']} ({', '.join(ac['requirement_ids'])})", "",
                  f"- **Given** {ac['given']}", f"- **When** {ac['when']}", f"- **Then** {ac['then']}", ""]
    lines += ["## Rủi ro", "", *bullets(prd["risks"]), "", "## Câu hỏi mở", "", *bullets(prd["open_questions"]), ""]
    return "\n".join(lines + resolution_lines(prd["resolutions"]))


def techspec_md(spec, round_):
    lines = ["# Techspec", "", f"Bản nháp vòng {round_}.", "", *brief_lines(spec.get("brief")),
             *assumption_lines(spec.get("assumptions")), "## Chi tiết", "", spec["summary"], "", "## Cách tiếp cận", "",
             spec["approach"], "", "## Thành phần", ""]
    for component in spec["components"]:
        lines += [f"- **{component['name']}**: {component['change']}"
                  + (f" (`{'`, `'.join(component['files'])}`)" if component["files"] else "")]
    lines += ["", "## Thay đổi dữ liệu", "", *bullets(spec["data_changes"]), "", "## Thay đổi API", "",
              *bullets(spec["api_changes"]), "", "## Bất biến phải giữ", "", *bullets(spec["invariants"]), "",
              "## Failure modes", "", "| Tình huống | Xử lý |", "| --- | --- |"]
    lines += [f"| {f['case']} | {f['handling']} |" for f in spec["failure_modes"]]
    lines += ["", "## Test plan", "", "| ID | Mức | Bao phủ | Mô tả |", "| --- | --- | --- | --- |"]
    lines += [f"| {t['id']} | {t['level']} | {', '.join(t['covers'])} | {t['description']} |" for t in spec["test_plan"]]
    lines += ["", "## Task", ""]
    lines += [f"- **{t['id']}** {t['title']}: {t['description']}" for t in spec["tasks"]]
    lines += ["", "## Rollout", "", *bullets(spec["rollout"]), "", "## Câu hỏi mở", "",
              *bullets(spec["open_questions"]), ""]
    return "\n".join(lines + resolution_lines(spec["resolutions"]))


def uxspec_md(spec, round_):
    lines = ["# Đặc tả UX", "", f"Bản nháp vòng {round_}.", "", *brief_lines(spec.get("brief")),
             "## Chi tiết", "", spec["summary"], "", "## Người dùng", "",
             *bullets(spec["users"]), "", "## Hành trình", ""]
    for journey in spec["journeys"]:
        covers = f" (bao phủ {', '.join(journey['covers'])})" if journey["covers"] else ""
        lines += [f"### {journey['id']}: {journey['goal']}{covers}", "",
                  *[f"{n}. {step}" for n, step in enumerate(journey["steps"], 1)], ""]
    lines += ["## Trạng thái", "", "| ID | Ở đâu | Trạng thái | Hành vi |", "| --- | --- | --- | --- |"]
    lines += [f"| {s['id']} | {s['where']} | {s['state']} | {s['behaviour']} |" for s in spec["states"]]
    lines += ["", "## Thành phần", ""]
    lines += [f"- **{c['name']}**: {c['reuse']}" for c in spec["components"]] or ["- Không có."]
    lines += ["", "## Nội dung chữ", ""]
    lines += [f"- `{c['key']}`: {c['text']}" for c in spec["copy"]] or ["- Không có."]
    lines += ["", "## Accessibility", "", *bullets(spec["accessibility"]), "", "## Màn hình hẹp", "",
              *bullets(spec["responsive"]), "", "## Quyết định thiết kế", ""]
    lines += [f"- **{d['question']}** Chọn: {d['choice']} (các phương án: {', '.join(d['options'])}). {d['reason']}"
              for d in spec["decisions"]] or ["- Không có."]
    lines += ["", "## Câu hỏi mở", "", *bullets(spec["open_questions"]), ""]
    return "\n".join(lines + resolution_lines(spec["resolutions"]))


def resolution_lines(resolutions):
    if not resolutions:
        return []
    return ["## Xử lý góp ý vòng trước", "", *[f"- `{r['finding_id']}` {r['disposition']}: {r['reason']}"
                                                for r in resolutions], ""]


def finding_lines(findings):
    if not findings:
        return ["Không có finding."]
    order = {"blocker": 0, "major": 1, "minor": 2}
    lines = []
    for f in sorted(findings, key=lambda f: order[f["severity"]]):
        where = f.get("target") or (f"{f['file']}:{f['line']}" if f.get("file") else "chung")
        lines.append(f"- **{f['severity']}** `{f['id']}` ({where}): {f['reason']} Gợi ý: {f['suggestion']}")
    return lines


def gate_md(kind, task_id, state, extra):
    titles = {"research": "Cần nguồn cho research", "prd": "Duyệt PRD", "uxspec": "Duyệt đặc tả UX",
              "techspec": "Duyệt techspec",
              "release": "Duyệt bàn giao code", "blocked": "Flow bị chặn"}
    risk = state.get("risk", "?")
    lines = [f"# {titles[kind]} — {task_id}", "", f"Rủi ro hiện tại: **{risk}**.", ""]
    lines += extra  # the plain layer comes first; triage is detail
    triage = state.get("triage")
    if triage:
        lines += ["### Triage", "", triage["summary"], "", f"Lý do mức rủi ro (model đề xuất {triage['risk']}): "
                  f"{triage['risk_reason']}", ""]
    lines += ["## Lệnh trả lời", "", "```bash"]
    if kind == "research":
        lines += [f".venv/bin/python run_flow.py research {task_id} --brief <brief-có-Source.md>",
                  f".venv/bin/python run_flow.py approve {task_id}   # bỏ qua research"]
    elif kind == "blocked":
        lines += [f".venv/bin/python run_flow.py retry {task_id} [--max-calls N] [--timeout S]   # sau khi đã xem log"]
        node = (state.get("blocked") or {}).get("node")
        if node == "research":
            lines += [f".venv/bin/python run_flow.py approve {task_id}   # tiếp tục với research thiếu coverage"]
        if node == "baseline":
            lines += [f".venv/bin/python run_flow.py approve {task_id}   # chạy tiếp dù lệnh test không chạy được"]
    else:
        lines += [f".venv/bin/python run_flow.py approve {task_id} [--risk P0..P3] [--note '...']",
                  f".venv/bin/python run_flow.py revise {task_id} --note 'cần sửa gì'"]
    lines += [f".venv/bin/python run_flow.py reject {task_id} --note 'lý do'", "```", ""]
    return "\n".join(lines)


def decision_lines(asks, task_id):
    """Questions only a person can answer, written so the answer fits in one revise note."""
    if not asks:
        return []
    lines = ["## Cần bạn quyết định", "",
             "Đây là lựa chọn nghiệp vụ mà request, rule và repo không trả lời được, nên AI không tự đặt quy tắc. "
             "Lỗi đúng/sai, an toàn và dữ liệu không nằm ở đây: AI tự sửa những lỗi đó.", ""]
    for number, f in enumerate(asks, 1):
        mark = "⚠ " if f.get("critical") else ""
        lines += [f"### Q{number}. {mark}{f['reason']}", ""]
        lines += [f"{n}. {option}" for n, option in enumerate(f.get("options") or [], 1)]
        lines += ["", f"Reviewer khuyên: {f['suggestion']}"]
        if f.get("author_choice"):
            agree = ("2 AI độc lập cùng ý kiến." if f.get("agrees_with_author")
                     else "**2 AI không thống nhất: nên đọc kỹ câu này.**")
            lines += [f"AI soạn tài liệu đang chọn: {f['author_choice']}. {agree}"]
        if f.get("critical"):
            lines += ["⚠ Quan trọng: chọn sai có thể mất tiền, lộ dữ liệu hoặc quyền, hay không hoàn tác được. "
                      "Câu này phải được trả lời riêng, không nhận 'ok' chung."]
        lines += [f"(finding `{f['id']}`, mục `{f.get('target') or 'chung'}`)", ""]
    example = "; ".join(f"Q{n}: chọn 1" for n in range(1, len(asks) + 1))
    lines += ["Trả lời cả lô trong một lệnh, tác giả sẽ sửa tài liệu theo đó. `--accept-recommendations` nhận "
              "đề xuất của reviewer cho các câu không có ⚠ mà bạn không ghi:", "", "```bash",
              f".venv/bin/python run_flow.py revise {task_id} --note '{example}'",
              f".venv/bin/python run_flow.py revise {task_id} --accept-recommendations [--note 'Q2: ...']", "```", ""]
    return lines


def doc_gate_extra(name, path, findings, reviews, why="", task_id="<task>", doc=None):
    unresolved = [f for f in findings if f["severity"] in BLOCKING]
    asks = decisions(findings)
    doc = doc or {}
    lines = [f"## {name}", "", f"Flow dừng ở đây vì: {why}.", ""] if why else [f"## {name}", ""]
    lines += decision_lines(asks, task_id)
    lines += brief_lines(doc.get("brief"))
    lines += assumption_lines(doc.get("assumptions") or [
        {"question": d["question"], "choice": d["choice"], "reason": d["reason"]} for d in doc.get("decisions", [])])
    lines += ["## Chi tiết cho người đọc kỹ", "", f"Bản đầy đủ: [{path}]({path})", "", "### Nhận xét của reviewer", ""]
    lines += [f"- **{persona}**: {summary}" for persona, summary in reviews.items()] or ["- Không có."]
    lines += ["", f"### Finding còn mở ({len(unresolved)} blocker/major)", "",
              *finding_lines([f for f in findings if f not in asks]), ""]
    return lines


def release_extra(state, commits, stat, tests_log):
    impl = state["implementation"]
    tests = state.get("tests", {})
    findings = state.get("code_findings", [])
    baseline = state.get("baseline") or {}
    brief = impl.get("brief") or {}
    open_count = len([f for f in findings if f["severity"] in BLOCKING])
    plain = {"passed": "đạt", "failed": "không đạt", "timeout": "quá giờ", "error": "không chạy được",
             "not_configured": "chưa cấu hình lệnh test"}
    lines = ["## Tóm tắt dễ đọc", ""]
    for title, key in (("Đã thay đổi gì", "what_changed"), ("Tự kiểm tra trên sản phẩm", "how_to_check"),
                       ("Còn hạn chế", "known_limits")):
        if brief.get(key):
            lines += [f"**{title}:**", "", *[f"{n}. {i}" if key == "how_to_check" else f"- {i}"
                                             for n, i in enumerate(brief[key], 1)], ""]
    lines += [f"- Test tự động: **{plain.get(tests.get('status'), tests.get('status', 'chưa chạy'))}**.",
              f"- Reviewer AI còn nêu **{open_count}** vấn đề blocker/major." if open_count
              else "- Reviewer AI không còn vấn đề blocker/major.",
              *(["- Các quyết định của task được ghi vào `docs/flow-decisions.md` trên nhánh này."]
                if decision_rows(state) else []), "",
              "## Chi tiết cho người đọc kỹ", "", "### Kết quả", "", f"- Nhánh: `{impl['branch']}` (chưa merge; quyền merge thuộc về người)",
             f"- Vòng implement: {state['impl_round']}", f"- Test: **{tests.get('status', 'chưa chạy')}**"
             + (f" — log: [{tests_log}]({tests_log})" if tests_log else "")]
    if baseline.get("log"):
        lines.append(f"- Test trên commit gốc, trước khi AI sửa: {baseline['status']} — log: "
                     f"[../{baseline['log']}](../{baseline['log']})")
    lines += ["", "## Commit", "",
             *bullets(commits, "Không có commit."), "", "## Diff", "", "```", stat.rstrip(), "```", "",
             "## Tóm tắt của implementer (lời khai của model)", "", impl["summary"], ""]
    acceptance = state.get("acceptance", {})
    if acceptance:
        lines += ["## Acceptance criteria theo reviewer", "", "| Reviewer | ID | Trạng thái | Lý do |",
                  "| --- | --- | --- | --- |"]
        lines += [f"| {persona} | {a['id']} | {a['status']} | {a['reason']} |"
                  for persona, items in acceptance.items() for a in items]
        lines.append("")
    lines += ["### Finding của vòng review cuối", "", *finding_lines(findings), ""]
    if impl.get("permission_denials"):
        lines += ["## Lệnh bị chặn trong lúc implement", "", f"- {impl['permission_denials']}", ""]
    return lines


def report_md(task_id, state, calls, max_calls):
    status = state.get("status", "running")
    lines = [f"# Task {task_id}", "", f"Trạng thái: **{status}**. Rủi ro: **{state.get('risk', '?')}**.", "",
             "AI soạn tài liệu, code và review; các quyết định ở cổng duyệt do người đưa ra. "
             "Flow không merge, push hay deploy.", "", "## Quyết định của người", ""]
    lines += [f"- {d['gate']}: **{d['action']}**" + (f" — {d['note']}" if d.get("note") else "")
              for d in state.get("decisions", [])] or ["- Chưa có."]
    lines += ["", "## Artifact", ""]
    if state.get("research"):
        lines.append(f"- Research: {state['research'].get('status')} ({state['research'].get('dir', '-')})")
    if state.get("prd"):
        lines.append("- [PRD](docs/prd.md)")
    if state.get("uxspec"):
        lines.append("- [Đặc tả UX](docs/uxspec.md)")
    if state.get("techspec"):
        lines.append("- [Techspec](docs/techspec.md)")
    if state.get("implementation"):
        impl = state["implementation"]
        lines.append(f"- Nhánh `{impl['branch']}` tại `{impl['head'][:12]}`; test: {state.get('tests', {}).get('status')}")
    lines += ["", "## Ngân sách", "", f"- Lượt gọi model đã bắt đầu: {calls}/{max_calls} (chưa tính research).",
              "- Giới hạn lượt gọi và timeout không phải hard cap tiền.", ""]
    return "\n".join(lines)


DECISIONS_HEADER = """# Quyết định của dự án

Flow ghi vào đây các lựa chọn nghiệp vụ và giả định của từng task. Task sau đọc file này như rule của dự án:
giữ nguyên các quyết định này, trừ khi request mới nói rõ là đổi. Dòng "AI tự quyết" là giả định chưa được
người xác nhận; dòng "Người duyệt chấp nhận đề xuất AI" là người đồng ý mà không tự chọn.
"""
WHO = {"person": "Người duyệt", "accepted-ai-recommendation": "Người duyệt chấp nhận đề xuất AI", "ai": "AI tự quyết"}


def decision_rows(state):
    """Questions people answered, then the assumptions the documents settled themselves."""
    rows = [(e["question"], e["choice"], WHO[e["by"]], "⚠ quan trọng" if e.get("critical") else "")
            for e in state.get("decision_log", [])]
    for doc in ("prd", "uxspec", "techspec"):
        spec = state.get(doc) or {}
        for a in spec.get("assumptions") or spec.get("decisions") or []:
            rows.append((a["question"], a["choice"], WHO["ai"], a["reason"]))
    return rows


def cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def decision_section(task_id, title, rows):
    return "\n".join([f"<!-- flow:{task_id} -->", f"## {cell(title)}", "", f"Task `{task_id}`.", "",
                      "| Câu hỏi | Lựa chọn | Ai quyết | Ghi chú |", "| --- | --- | --- | --- |",
                      *[f"| {cell(q)} | {cell(c)} | {w} | {cell(n)} |" for q, c, w, n in rows],
                      f"<!-- /flow:{task_id} -->", ""])


def replace_section(text, task_id, section):
    start, end = f"<!-- flow:{task_id} -->", f"<!-- /flow:{task_id} -->\n"
    if start in text and end in text:
        head, rest = text.split(start, 1)
        return head + section + rest.split(end, 1)[1]
    return text.rstrip("\n") + "\n\n" + section
