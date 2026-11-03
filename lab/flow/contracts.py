"""Structured outputs for the work flow and the supervisor's deterministic checks.

Hard checks (unique IDs, references that exist, findings resolved exactly once)
reject an output. Soft checks (a must-requirement without acceptance criteria,
an acceptance criterion without a test, a claimed file that did not change)
become supervisor findings, so reviewers and the human gate see them without
burning a call on a rejected output.
"""
import copy

from ..contracts import TEXT, array, exact_coverage, nonblank, obj

RISKS = ("P0", "P1", "P2", "P3")  # P0 is the most severe tier
SEVERITIES = ("blocker", "major", "minor")
BLOCKING = {"blocker", "major"}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}


def enum(*values):
    return {"type": "string", "enum": list(values)}


RESOLUTION = obj({"finding_id": TEXT, "disposition": enum("fixed", "rejected"), "reason": TEXT})
TRIAGE = obj({"summary": TEXT, "risk": enum(*RISKS), "risk_reason": TEXT, "needs_research": BOOL,
              "research_questions": array(TEXT), "affected_areas": array(TEXT), "open_questions": array(TEXT)})
PRD = obj({"title": TEXT, "summary": TEXT, "problem": TEXT, "goals": array(TEXT), "non_goals": array(TEXT),
           "users": array(TEXT),
           "requirements": array(obj({"id": TEXT, "text": TEXT, "priority": enum("must", "should", "could")})),
           "acceptance_criteria": array(obj({"id": TEXT, "requirement_ids": array(TEXT),
                                             "given": TEXT, "when": TEXT, "then": TEXT})),
           "risks": array(TEXT), "open_questions": array(TEXT), "resolutions": array(RESOLUTION)})
TECHSPEC = obj({"summary": TEXT, "approach": TEXT,
                "components": array(obj({"name": TEXT, "change": TEXT, "files": array(TEXT)})),
                "data_changes": array(TEXT), "api_changes": array(TEXT), "invariants": array(TEXT),
                "failure_modes": array(obj({"case": TEXT, "handling": TEXT})),
                "test_plan": array(obj({"id": TEXT, "covers": array(TEXT),
                                        "level": enum("unit", "integration", "e2e", "manual"), "description": TEXT})),
                "tasks": array(obj({"id": TEXT, "title": TEXT, "description": TEXT, "files": array(TEXT)})),
                "rollout": array(TEXT), "open_questions": array(TEXT), "resolutions": array(RESOLUTION)})
DOC_REVIEW = obj({"summary": TEXT, "findings": array(obj({
    "id": TEXT, "target": TEXT, "severity": enum(*SEVERITIES), "reason": TEXT, "suggestion": TEXT})),
    "limitations": array(TEXT)})
IMPLEMENT = obj({"summary": TEXT, "changes": array(obj({"file": TEXT, "description": TEXT})),
                 "tests": array(obj({"file": TEXT, "covers": array(TEXT)})),
                 "commands_run": array(obj({"command": TEXT, "exit_code": INT, "note": TEXT})),
                 "resolutions": array(obj({"finding_id": TEXT, "disposition": enum("fixed", "rejected", "deferred"),
                                           "reason": TEXT})),
                 "open_questions": array(TEXT)})
CODE_REVIEW = obj({"summary": TEXT, "findings": array(obj({
    "id": TEXT, "severity": enum(*SEVERITIES),
    "kind": enum("correctness", "security", "payment-invariant", "data-integrity", "test-gap",
                 "spec-mismatch", "rule-violation", "maintainability", "other"),
    "file": TEXT, "line": INT, "reason": TEXT, "suggestion": TEXT})),
    "acceptance": array(obj({"id": TEXT, "status": enum("met", "not_met", "unverified"), "reason": TEXT})),
    "limitations": array(TEXT)})
SCHEMAS = {"triage": TRIAGE, "prd": PRD, "techspec": TECHSPEC, "doc-review": DOC_REVIEW,
           "implement": IMPLEMENT, "code-review": CODE_REVIEW}

PRD_SECTIONS = ["overall", "problem", "goals", "non_goals", "users", "risks", "open_questions"]
TECHSPEC_SECTIONS = ["overall", "approach", "components", "data_changes", "api_changes", "invariants",
                     "failure_modes", "test_plan", "tasks", "rollout", "open_questions"]


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
            nonblank(criterion[key])
        if not criterion["requirement_ids"] or not set(criterion["requirement_ids"]) <= set(requirement_ids):
            raise ValueError(f"Acceptance criterion {criterion['id']} cites an unknown requirement")
    check_resolutions(prd["resolutions"], required)


def prd_lint(prd):
    covered = {rid for a in prd["acceptance_criteria"] for rid in a["requirement_ids"]}
    return [{"id": f"S-{r['id']}", "target": r["id"], "severity": "major",
             "reason": "Requirement 'must' chưa có acceptance criterion nào kiểm được.",
             "suggestion": "Thêm acceptance criterion Given/When/Then cho requirement này."}
            for r in prd["requirements"] if r["priority"] == "must" and r["id"] not in covered]


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
    return findings


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


def implement_lint(out, changed):
    """Compare the implementer's claims with the actual diff of this round."""
    changed = set(changed)
    findings = []
    if not changed:
        findings.append({"id": "S-empty", "severity": "blocker", "kind": "spec-mismatch", "file": "", "line": 0,
                         "reason": "Vòng implement không tạo thay đổi nào trong worktree.",
                         "suggestion": "Triển khai thay đổi hoặc nêu rõ vì sao không cần sửa code."})
    claimed = {c["file"] for c in out["changes"]} | {t["file"] for t in out["tests"]}
    for index, file in enumerate(sorted(claimed - changed), 1):
        findings.append({"id": f"S-claim{index}", "severity": "major", "kind": "spec-mismatch", "file": "",
                         "line": 0, "reason": f"Báo cáo implement nêu đã sửa {file} nhưng diff vòng này không có file đó.",
                         "suggestion": "Đối chiếu báo cáo với diff thực tế."})
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


def acceptance_findings(source, acceptance):
    return [{"id": f"{source}/AC-{a['id']}", "source": source, "severity": "major", "kind": "spec-mismatch",
             "file": "", "line": 0, "reason": f"Reviewer đánh giá {a['id']} chưa đạt: {a['reason']}",
             "suggestion": "Sửa để criterion đạt, hoặc phản bác bằng bằng chứng trong code/test."}
            for a in acceptance if a["status"] == "not_met"]
