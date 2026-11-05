"""Structured outputs for the work flow and the supervisor's deterministic checks.

Hard checks (unique IDs, references that exist, findings resolved exactly once)
reject an output. Soft checks (a must-requirement without acceptance criteria,
an acceptance criterion without a test, a claimed file that did not change)
become supervisor findings, so reviewers and the human gate see them without
burning a call on a rejected output.
"""
import copy
import re

from ..contracts import TEXT, array, exact_coverage, nonblank, obj

RISKS = ("P0", "P1", "P2", "P3")  # P0 is the most severe tier
SEVERITIES = ("blocker", "major", "minor")
BLOCKING = {"blocker", "major"}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def described(text):
    return {**TEXT, "description": text}


# Without these descriptions models tended to write "When ...; Then ..." into `when` and leave `then` empty.
GIVEN = described("Precondition or starting state only. No action and no outcome.")
WHEN = described("The action or event under test only. Never the expected outcome: that belongs in `then`.")
THEN = described("Required and non-empty. The observable expected outcome a test or a person checks. "
                 "Do not repeat it in `when`.")
RESOLUTION = obj({"finding_id": TEXT, "disposition": enum("fixed", "rejected"), "reason": TEXT})


def plain(text):
    return {**array(TEXT), "description": text + " Everyday words a non-engineer understands: no IDs, code names, "
                                                 "file paths or jargon."}


# The short layer every person reads; the rest of the document is for whoever reviews in depth.
DOC_BRIEF = {**obj({"what_changes": plain("What users or the business will notice after this work, one item per line."),
                    "main_flow": plain("The main flow after the change as 3-6 ordered steps."),
                    "not_doing": plain("What this work deliberately leaves out."),
                    "risks": plain("What could still go wrong for users or the business.")}),
             "description": "A one-screen summary that matches the document; it must not hide or soften a risk."}
ASSUMPTIONS = {**array(obj({"question": TEXT, "choice": TEXT, "reason": TEXT})), "description": (
    "Choices you settled yourself because the request, rules or code settle them, or because a sensible, "
    "reversible default exists (a timeout, wording, placement). One item each; a person may overrule them. "
    "A business policy the request leaves open (fees, limits, who may do what, scope) belongs in open_questions.")}
IMPLEMENT_BRIEF = obj({"what_changed": plain("What users will notice now, one item per line."),
                       "how_to_check": plain("3-5 steps a person can follow in the running product to see it work."),
                       "known_limits": plain("What is still not handled or not verified.")})
TRIAGE = obj({"summary": TEXT, "risk": enum(*RISKS), "risk_reason": TEXT, "needs_research": BOOL,
              "research_questions": array(TEXT), "affected_areas": array(TEXT), "open_questions": array(TEXT)})
PRD = obj({"title": TEXT, "summary": TEXT, "problem": TEXT, "goals": array(TEXT), "non_goals": array(TEXT),
           "users": array(TEXT),
           "requirements": array(obj({"id": TEXT, "text": TEXT, "priority": enum("must", "should", "could")})),
           "acceptance_criteria": array(obj({"id": TEXT, "requirement_ids": array(TEXT),
                                             "given": GIVEN, "when": WHEN, "then": THEN})),
           "risks": array(TEXT), "open_questions": array(TEXT), "resolutions": array(RESOLUTION),
           "brief": DOC_BRIEF, "assumptions": ASSUMPTIONS})
TECHSPEC = obj({"summary": TEXT, "approach": TEXT,
                "components": array(obj({"name": TEXT, "change": TEXT, "files": array(TEXT)})),
                "data_changes": array(TEXT), "api_changes": array(TEXT), "invariants": array(TEXT),
                "failure_modes": array(obj({"case": TEXT, "handling": TEXT})),
                "test_plan": array(obj({"id": TEXT, "covers": array(TEXT),
                                        "level": enum("unit", "integration", "e2e", "manual"), "description": TEXT})),
                "tasks": array(obj({"id": TEXT, "title": TEXT, "description": TEXT, "files": array(TEXT)})),
                "rollout": array(TEXT), "open_questions": array(TEXT), "resolutions": array(RESOLUTION),
                "brief": DOC_BRIEF, "assumptions": ASSUMPTIONS})
UX_STATES = ("loading", "empty", "error", "permission", "success", "partial")
UXSPEC = obj({"summary": TEXT, "users": array(TEXT),
              "journeys": array(obj({"id": TEXT, "goal": TEXT, "steps": array(TEXT), "covers": array(TEXT)})),
              "states": array(obj({"id": TEXT, "where": TEXT, "state": enum(*UX_STATES), "behaviour": TEXT})),
              "components": array(obj({"name": TEXT, "reuse": TEXT})),
              "copy": array(obj({"key": TEXT, "text": TEXT})),
              "accessibility": array(TEXT), "responsive": array(TEXT),
              "decisions": array(obj({"question": TEXT, "options": array(TEXT), "choice": TEXT, "reason": TEXT})),
              "open_questions": array(TEXT), "resolutions": array(RESOLUTION), "brief": DOC_BRIEF})
# A finding the author cannot fix without inventing a business or product rule goes to a person at once:
# another drafting round would only guess, and the next review would flag the guess.
NEEDS_DECISION = {**BOOL, "description": (
    "True only for a business or product policy that the request, rules and repository leave open and on which "
    "two reasonable product owners could choose differently (fees, limits, who may do what, scope). Never for "
    "correctness, safety, security or data integrity, nor for anything the request's goal, a rule or an "
    "invariant already settles: those are ordinary findings the author fixes. Never for a reversible detail "
    "with a sensible default: the author picks it as an assumption. When true, write `reason` as the question "
    "in everyday words, list the choices in `options` and put the recommended choice and why in `suggestion`.")}
OPTIONS = {**array(TEXT), "description": ("Two to four choices when needs_decision is true, each acceptable for the "
                                          "product and stated with its consequence for users; empty otherwise.")}
CRITICAL = {**BOOL, "description": "With needs_decision: a wrong choice loses money, exposes data or permissions, or "
                                   "cannot be undone. False otherwise."}
AUTHOR_CHOICE = {**TEXT, "description": "With needs_decision: what the document currently chooses or assumes for this "
                                        "question, empty if it says nothing."}
AGREES = {**BOOL, "description": "With needs_decision: true when your recommendation matches author_choice."}
DOC_REVIEW = obj({"summary": TEXT, "findings": array(obj({
    "id": TEXT, "target": TEXT, "severity": enum(*SEVERITIES), "reason": TEXT, "suggestion": TEXT,
    "needs_decision": NEEDS_DECISION, "options": OPTIONS, "critical": CRITICAL, "author_choice": AUTHOR_CHOICE,
    "agrees_with_author": AGREES})),
    "limitations": array(TEXT)})
IMPLEMENT = obj({"summary": TEXT, "changes": array(obj({"file": TEXT, "description": TEXT})),
                 "tests": array(obj({"file": TEXT, "covers": array(TEXT)})),
                 "commands_run": array(obj({"command": TEXT, "exit_code": INT, "note": TEXT})),
                 "resolutions": array(obj({"finding_id": TEXT, "disposition": enum("fixed", "rejected", "deferred"),
                                           "reason": TEXT})),
                 "open_questions": array(TEXT), "brief": IMPLEMENT_BRIEF})
CODE_REVIEW = obj({"summary": TEXT, "findings": array(obj({
    "id": TEXT, "severity": enum(*SEVERITIES),
    "kind": enum("correctness", "security", "payment-invariant", "data-integrity", "test-gap",
                 "spec-mismatch", "rule-violation", "maintainability", "accuracy", "clarity", "voice",
                 "unsupported-claim", "usability", "accessibility", "other"),
    "file": TEXT, "line": INT, "reason": TEXT, "suggestion": TEXT})),
    "acceptance": array(obj({"id": TEXT, "status": enum("met", "not_met", "unverified"), "reason": TEXT})),
    "limitations": array(TEXT)})
SCHEMAS = {"triage": TRIAGE, "prd": PRD, "techspec": TECHSPEC, "uxspec": UXSPEC, "doc-review": DOC_REVIEW,
           "implement": IMPLEMENT, "code-review": CODE_REVIEW}

PRD_SECTIONS = ["overall", "brief", "assumptions", "problem", "goals", "non_goals", "users", "risks", "open_questions"]
UXSPEC_SECTIONS = ["overall", "brief", "users", "components", "copy", "accessibility", "responsive", "decisions",
                   "open_questions"]
TECHSPEC_SECTIONS = ["overall", "brief", "assumptions", "approach", "components", "data_changes", "api_changes",
                     "invariants", "failure_modes", "test_plan", "tasks", "rollout", "open_questions"]


def restrict(schema, path, values):
    """Narrow a string field to known IDs so the CLI's structured output cannot invent one."""
    schema = copy.deepcopy(schema)
    if values:
        # deepcopy keeps shared sub-dicts (TEXT) shared, so assign a new node, never mutate one.
        parent = schema
        for key in path[:-1]:
            parent = parent["properties"][key] if key != "[]" else parent["items"]
        replacement = {"type": "string", "enum": list(dict.fromkeys(values))}
        if path[-1] == "[]":
            parent["items"] = replacement
        else:
            parent["properties"][path[-1]] = replacement
    return schema


def most_severe(*risks):
    return min((r for r in risks if r), key=RISKS.index)


def ids(items, what):
    values = [item["id"] for item in items]
    if any(not v.strip() for v in values) or len(values) != len(set(values)):
        raise ValueError(f"Duplicate or blank {what} IDs")
    return values


def check_resolutions(resolutions, required):
    exact_coverage([r["finding_id"] for r in resolutions], required)
    for resolution in resolutions:
        nonblank(resolution["reason"])


def prd_targets(prd):
    return [*PRD_SECTIONS, *[r["id"] for r in prd["requirements"]], *[a["id"] for a in prd["acceptance_criteria"]]]


def techspec_targets(spec):
    return [*TECHSPEC_SECTIONS, *[t["id"] for t in spec["test_plan"]], *[t["id"] for t in spec["tasks"]]]


def uxspec_targets(spec):
    return [*UXSPEC_SECTIONS, *[j["id"] for j in spec["journeys"]], *[s["id"] for s in spec["states"]]]


def acceptance_ids(prd):
    return [a["id"] for a in prd["acceptance_criteria"]] if prd else []


def validate_triage(out):
    nonblank(out["summary"])
    nonblank(out["risk_reason"])


def validate_prd(prd, required):
    for key in ("title", "summary", "problem"):
        nonblank(prd[key])
    if not prd["requirements"] or not prd["acceptance_criteria"]:
        raise ValueError("PRD needs requirements and acceptance criteria")
    requirement_ids = ids(prd["requirements"], "requirement")
    criterion_ids = ids(prd["acceptance_criteria"], "acceptance criterion")
    if set(requirement_ids) & set(criterion_ids) or set(requirement_ids + criterion_ids) & set(PRD_SECTIONS):
        raise ValueError("Requirement, criterion and section IDs must be distinct")
    for requirement in prd["requirements"]:
        nonblank(requirement["text"])
    for criterion in prd["acceptance_criteria"]:
        for key in ("given", "when", "then"):
            try:
                nonblank(criterion[key])
            except ValueError:
                raise ValueError(f"Acceptance criterion {criterion['id']}: field '{key}' is empty") from None
        if not criterion["requirement_ids"] or not set(criterion["requirement_ids"]) <= set(requirement_ids):
            raise ValueError(f"Acceptance criterion {criterion['id']} cites an unknown requirement")
    check_resolutions(prd["resolutions"], required)


def brief_lint(doc):
    """The short layer is what most people read: an empty one is visible, but not worth another round."""
    brief = doc.get("brief") or {}
    if brief.get("what_changes") and brief.get("main_flow"):
        return []
    return [{"id": "S-brief", "target": "brief", "severity": "minor",
             "reason": "Thiếu tóm tắt dễ đọc (thay đổi người dùng thấy hoặc luồng chính).",
             "suggestion": "Viết brief bằng lời thường cho người không rành kỹ thuật."}]


def prd_lint(prd):
    covered = {rid for a in prd["acceptance_criteria"] for rid in a["requirement_ids"]}
    return [{"id": f"S-{r['id']}", "target": r["id"], "severity": "major",
             "reason": "Requirement 'must' chưa có acceptance criterion nào kiểm được.",
             "suggestion": "Thêm acceptance criterion Given/When/Then cho requirement này."}
            for r in prd["requirements"] if r["priority"] == "must" and r["id"] not in covered] + brief_lint(prd)


def validate_techspec(spec, prd, required):
    nonblank(spec["summary"])
    nonblank(spec["approach"])
    plan_ids = ids(spec["test_plan"], "test plan")
    task_ids = ids(spec["tasks"], "task")
    if set(plan_ids) & set(task_ids) or set(plan_ids + task_ids) & set(TECHSPEC_SECTIONS):
        raise ValueError("Test plan, task and section IDs must be distinct")
    known = set(acceptance_ids(prd))
    for entry in spec["test_plan"]:
        nonblank(entry["description"])
        if known and not set(entry["covers"]) <= known:
            raise ValueError(f"Test plan {entry['id']} covers an unknown acceptance criterion")
    for task in spec["tasks"]:
        nonblank(task["title"])
    check_resolutions(spec["resolutions"], required)


def techspec_lint(spec, prd):
    covered = {ac for entry in spec["test_plan"] for ac in entry["covers"]}
    findings = [{"id": f"S-{ac}", "target": "test_plan", "severity": "major",
                 "reason": f"Acceptance criterion {ac} chưa có mục test plan nào bao phủ.",
                 "suggestion": "Thêm test (ưu tiên tự động) chứng minh criterion này."}
                for ac in acceptance_ids(prd) if ac not in covered]
    if not spec["tasks"]:
        findings.append({"id": "S-tasks", "target": "tasks", "severity": "major",
                         "reason": "Techspec chưa chia task triển khai.", "suggestion": "Liệt kê task và file dự kiến."})
    return findings + brief_lint(spec)


def validate_uxspec(spec, prd, required):
    nonblank(spec["summary"])
    if not spec["journeys"]:
        raise ValueError("UX spec needs at least one journey")
    journey_ids = ids(spec["journeys"], "journey")
    state_ids = ids(spec["states"], "state")
    if set(journey_ids) & set(state_ids) or set(journey_ids + state_ids) & set(UXSPEC_SECTIONS):
        raise ValueError("Journey, state and section IDs must be distinct")
    known = set(acceptance_ids(prd))
    for journey in spec["journeys"]:
        nonblank(journey["goal"])
        if not journey["steps"]:
            raise ValueError(f"Journey {journey['id']} has no steps")
        if known and not set(journey["covers"]) <= known:
            raise ValueError(f"Journey {journey['id']} covers an unknown acceptance criterion")
    for state in spec["states"]:
        nonblank(state["behaviour"])
    check_resolutions(spec["resolutions"], required)


def uxspec_lint(spec, prd):
    covered = {ac for journey in spec["journeys"] for ac in journey["covers"]}
    findings = [{"id": f"S-{ac}", "target": "overall", "severity": "major",
                 "reason": f"Acceptance criterion {ac} chưa có hành trình người dùng nào bao phủ.",
                 "suggestion": "Thêm hoặc mở rộng một journey cho criterion này."}
                for ac in acceptance_ids(prd) if ac not in covered]
    if "error" not in {s["state"] for s in spec["states"]}:
        findings.append({"id": "S-error", "target": "overall", "severity": "major",
                         "reason": "Đặc tả chưa mô tả trạng thái lỗi.",
                         "suggestion": "Mô tả điều người dùng thấy và làm được khi thao tác thất bại."})
    if not spec["accessibility"]:
        findings.append({"id": "S-a11y", "target": "accessibility", "severity": "major",
                         "reason": "Đặc tả chưa có yêu cầu accessibility.",
                         "suggestion": "Nêu cách dùng bằng bàn phím, nhãn cho trình đọc màn hình và độ tương phản."})
    return findings + brief_lint(spec)


def validate_doc_review(review, targets):
    nonblank(review["summary"])
    ids(review["findings"], "finding")
    for finding in review["findings"]:
        if finding["target"] not in targets:
            raise ValueError(f"Unknown review target: {finding['target']}")
        nonblank(finding["reason"])
        nonblank(finding["suggestion"])


def validate_implement(out, required):
    nonblank(out["summary"])
    exact_coverage([r["finding_id"] for r in out["resolutions"]], required)
    for resolution in out["resolutions"]:
        nonblank(resolution["reason"])


def implement_lint(out, changed, tree):
    """Compare the implementer's claims with the real diff of this round (`changed`) and the files at the
    new tip (`tree`). `tests` names the tests that cover the work, which may come from an earlier round,
    so a test file only has to exist; `changes` claims an edit in this round, so it must be in the diff."""
    changed, tree = set(changed), set(tree)
    findings = []
    claims_fix = not out["resolutions"] or any(r["disposition"] == "fixed" for r in out["resolutions"])
    if not changed and claims_fix:  # rejecting every finding with evidence needs no edit
        findings.append({"id": "S-empty", "severity": "blocker", "kind": "spec-mismatch", "file": "", "line": 0,
                         "reason": "Vòng implement không tạo thay đổi nào trong worktree.",
                         "suggestion": "Triển khai thay đổi hoặc nêu rõ vì sao không cần sửa code."})
    unchanged = sorted({c["file"] for c in out["changes"]} - changed)
    missing = sorted({t["file"] for t in out["tests"]} - tree - changed)
    for index, (file, reason) in enumerate(
            [(f, f"Báo cáo implement nêu đã sửa {f} nhưng diff vòng này không có file đó.") for f in unchanged]
            + [(f, f"Báo cáo implement nêu test {f} nhưng file này không có trong worktree.") for f in missing], 1):
        findings.append({"id": f"S-claim{index}", "severity": "major", "kind": "spec-mismatch", "file": "",
                         "line": 0, "reason": reason, "suggestion": "Đối chiếu báo cáo với diff thực tế."})
    return findings


def validate_code_review(review, criteria, files):
    nonblank(review["summary"])
    ids(review["findings"], "finding")
    for finding in review["findings"]:
        if finding["file"] and finding["file"] not in files:
            raise ValueError(f"Finding cites a file outside the worktree diff/tree: {finding['file']}")
        if finding["line"] < 0:
            raise ValueError("Finding line must be >= 0")
        nonblank(finding["reason"])
        nonblank(finding["suggestion"])
    exact_coverage([a["id"] for a in review["acceptance"]], criteria)
    for item in review["acceptance"]:
        nonblank(item["reason"])


def tag(findings, source):
    """Namespace reviewer-local IDs so findings from several reviewers never collide."""
    return [{**f, "id": f"{source}/{f['id']}", "source": source} for f in findings]


def blocking(findings):
    return [f for f in findings if f["severity"] in BLOCKING]


def decisions(findings):
    """Blocking findings that only a person can settle, critical ones first, numbered Q1.. in this order.
    A "question" with fewer than two options is no choice: it stays an ordinary finding the author fixes.
    Documents reviewed before these fields existed have none."""
    asks = [f for f in blocking(findings) if f.get("needs_decision") and len(f.get("options") or []) >= 2]
    return sorted(asks, key=lambda f: not f.get("critical"))


def parse_answers(note):
    """'Q2: chỉ quản trị viên; Q1: chọn 1' -> {2: 'chỉ quản trị viên', 1: 'chọn 1'}."""
    parts = re.split(r"\bQ(\d+)\s*[:.)\-]", note or "")
    return {int(number): text.strip(" ;,\n") for number, text in zip(parts[1::2], parts[2::2])}


def check_answers(critical, note, accept):
    """`critical` holds one flag per question Q1..Qn. Return the questions the note leaves to
    --accept-recommendations, or raise when a question is left unanswered."""
    answers = parse_answers(note)
    missing = [n for n in range(1, len(critical) + 1) if n not in answers]
    left = [n for n in missing if critical[n - 1]]
    if left:
        raise ValueError("Câu quan trọng phải được người trả lời riêng: "
                         + ", ".join(f"Q{n}" for n in left) + " (ghi 'Qn: <lựa chọn>' trong --note)")
    if missing and not accept:
        raise ValueError("Chưa trả lời " + ", ".join(f"Q{n}" for n in missing)
                         + ": ghi 'Qn: <lựa chọn>' trong --note hoặc thêm --accept-recommendations")
    return missing


def check_decision(gate, decision):
    """Validate a person's answer before the graph resumes. An error raised inside a resumed node would leave
    that answer recorded at the interrupt, so a corrected answer could never get through."""
    action, note = decision.get("action"), (decision.get("note") or "").strip()
    accept, questions = decision.get("accept"), gate.get("questions", [])
    if action not in gate["actions"]:
        raise ValueError(f"Gate {gate['kind']} accepts: {', '.join(gate['actions'])}")
    if accept and (action != "revise" or not questions):
        raise ValueError("--accept-recommendations chỉ dùng với revise ở cổng tài liệu có câu hỏi")
    if action == "revise" and not note and not accept:
        raise ValueError("revise needs a note describing the change")
    if questions and action == "approve":
        raise ValueError(f"Cổng này có {len(questions)} câu hỏi cho người quyết: trả lời bằng revise --note "
                         "'Q1: ...' hoặc revise --accept-recommendations")
    if questions and action == "revise":
        check_answers([q["critical"] for q in questions], note, accept)


def answer_decisions(asks, note, accept):
    """Map a revise note to each question. "Q2: ..." answers Q2; --accept-recommendations takes the reviewer's
    recommendation for the rest, except critical questions, which a person must answer by number."""
    missing = check_answers([bool(f.get("critical")) for f in asks], note, accept)
    answers = parse_answers(note)
    entries = [{"question": f["reason"], "options": f.get("options", []), "critical": bool(f.get("critical")),
                "choice": answers.get(n) or f["suggestion"],
                "by": "person" if n in answers else "accepted-ai-recommendation", "finding": f["id"]}
               for n, f in enumerate(asks, 1)]
    lines = [f"Q{n} ({e['finding']}): {e['choice']}" + ("" if e["by"] == "person" else " (người duyệt chấp nhận đề xuất)")
             for n, e in enumerate(entries, 1)]
    return entries, "\n".join(filter(None, [note.strip(), *([] if not missing else lines)]))


def acceptance_findings(source, acceptance):
    return [{"id": f"{source}/AC-{a['id']}", "source": source, "severity": "major", "kind": "spec-mismatch",
             "file": "", "line": 0, "reason": f"Reviewer đánh giá {a['id']} chưa đạt: {a['reason']}",
             "suggestion": "Sửa để criterion đạt, hoặc phản bác bằng bằng chứng trong code/test."}
            for a in acceptance if a["status"] == "not_met"]
