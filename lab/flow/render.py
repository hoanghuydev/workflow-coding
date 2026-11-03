"""Markdown views rendered by the supervisor from validated JSON."""
from .contracts import BLOCKING


def bullets(items, empty="Không có."):
    return [f"- {item}" for item in items] or [f"- {empty}"]


def prd_md(prd, round_):
    lines = [f"# PRD: {prd['title']}", "", f"Bản nháp vòng {round_}. Do AI soạn; xem cổng duyệt để biết trạng thái.", "",
             prd["summary"], "", "## Vấn đề", "", prd["problem"], "", "## Mục tiêu", "", *bullets(prd["goals"]), "",
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
    lines = ["# Techspec", "", f"Bản nháp vòng {round_}.", "", spec["summary"], "", "## Cách tiếp cận", "",
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
    titles = {"research": "Cần nguồn cho research", "prd": "Duyệt PRD", "techspec": "Duyệt techspec",
              "release": "Duyệt bàn giao code", "blocked": "Flow bị chặn"}
    risk = state.get("risk", "?")
    lines = [f"# {titles[kind]} — {task_id}", "", f"Rủi ro hiện tại: **{risk}**.", ""]
    triage = state.get("triage")
    if triage:
        lines += ["## Triage", "", triage["summary"], "", f"Lý do mức rủi ro (model đề xuất {triage['risk']}): "
                  f"{triage['risk_reason']}", ""]
    lines += extra
    lines += ["## Lệnh trả lời", "", "```bash"]
    if kind == "research":
        lines += [f".venv/bin/python run_flow.py research {task_id} --brief <brief-có-Source.md>",
                  f".venv/bin/python run_flow.py approve {task_id}   # bỏ qua research"]
    elif kind == "blocked":
        lines += [f".venv/bin/python run_flow.py retry {task_id} [--max-calls N]   # sau khi đã xem log"]
        if state.get("blocked", {}).get("node") == "research":
            lines += [f".venv/bin/python run_flow.py approve {task_id}   # tiếp tục với research thiếu coverage"]
    else:
        lines += [f".venv/bin/python run_flow.py approve {task_id} [--risk P0..P3] [--note '...']",
                  f".venv/bin/python run_flow.py revise {task_id} --note 'cần sửa gì'"]
    lines += [f".venv/bin/python run_flow.py reject {task_id} --note 'lý do'", "```", ""]
    return "\n".join(lines)


def doc_gate_extra(name, path, findings, reviews):
    unresolved = [f for f in findings if f["severity"] in BLOCKING]
    lines = [f"## {name}", "", f"Bản đọc: [{path}]({path})", "", "## Nhận xét của reviewer", ""]
    lines += [f"- **{persona}**: {summary}" for persona, summary in reviews.items()] or ["- Không có."]
    lines += ["", f"## Finding còn mở ({len(unresolved)} blocker/major)", "", *finding_lines(findings), ""]
    return lines


def release_extra(state, commits, stat, tests_log):
    impl = state["implementation"]
    tests = state.get("tests", {})
    findings = state.get("code_findings", [])
    lines = ["## Kết quả", "", f"- Nhánh: `{impl['branch']}` (chưa merge; quyền merge thuộc về người)",
             f"- Vòng implement: {state['impl_round']}", f"- Test: **{tests.get('status', 'chưa chạy')}**"
             + (f" — log: [{tests_log}]({tests_log})" if tests_log else ""), "", "## Commit", "",
             *bullets(commits, "Không có commit."), "", "## Diff", "", "```", stat.rstrip(), "```", "",
             "## Tóm tắt của implementer (lời khai của model)", "", impl["summary"], ""]
    acceptance = state.get("acceptance", {})
    if acceptance:
        lines += ["## Acceptance criteria theo reviewer", "", "| Reviewer | ID | Trạng thái | Lý do |",
                  "| --- | --- | --- | --- |"]
        lines += [f"| {persona} | {a['id']} | {a['status']} | {a['reason']} |"
                  for persona, items in acceptance.items() for a in items]
        lines.append("")
    lines += ["## Finding của vòng review cuối", "", *finding_lines(findings), ""]
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
    if state.get("techspec"):
        lines.append("- [Techspec](docs/techspec.md)")
    if state.get("implementation"):
        impl = state["implementation"]
        lines.append(f"- Nhánh `{impl['branch']}` tại `{impl['head'][:12]}`; test: {state.get('tests', {}).get('status')}")
    lines += ["", "## Ngân sách", "", f"- Lượt gọi model đã bắt đầu: {calls}/{max_calls} (chưa tính research).",
              "- Giới hạn lượt gọi và timeout không phải hard cap tiền.", ""]
    return "\n".join(lines)
