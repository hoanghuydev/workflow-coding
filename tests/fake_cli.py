"""Synthetic CLI process for offline supervisor tests; never calls a provider."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

if "--version" in sys.argv:
    print("synthetic-cli 1.0")
    sys.exit(0)

CORRECT_FEE = ("def transfer_fee(amount: int) -> int:\n    if amount < 0:\n"
               "        raise ValueError(\"amount must be non-negative\")\n    return -(-amount * 11 // 1000)\n")
BUGGY_FEE = "def transfer_fee(amount: int) -> int:\n    return amount * 11 // 1000\n"
ZERO_TEST = ("import unittest\n\nfrom fees import transfer_fee\n\n\nclass ZeroFeeTests(unittest.TestCase):\n"
             "    def test_zero_amount_has_zero_fee(self):\n        self.assertEqual(transfer_fee(0), 0)\n")


def flow_report(stage, context, behavior):
    """Synthetic outputs for the work flow; the implement stage edits the demo worktree."""
    resolutions = [{"finding_id": f["id"], "disposition": "fixed", "reason": "Synthetic resolution."}
                   for f in context.get("findings_to_resolve", [])]
    criteria = [a["id"] for a in (context.get("prd") or {}).get("acceptance_criteria", [])]
    if stage == "triage":
        return {"summary": "Synthetic triage.", "risk": behavior[5:] if behavior.startswith("risk_") else "P2",
                "risk_reason": "Synthetic fixture.", "needs_research": behavior == "needs_research",
                "research_questions": ["Which policy applies?"] if behavior == "needs_research" else [],
                "affected_areas": ["fees.py"], "open_questions": []}
    if stage == "prd":
        return {"title": "Phí chuyển khoản", "summary": "Synthetic PRD.", "problem": "Chưa có hàm tính phí.",
                "goals": ["Tính phí đúng"], "non_goals": ["Đổi biểu phí"], "users": ["Merchant"],
                "requirements": [{"id": "R1", "text": "Phí 1,1% làm tròn lên.", "priority": "must"},
                                 {"id": "R2", "text": "Từ chối số tiền âm.", "priority": "must"}],
                "acceptance_criteria": [
                    {"id": "AC1", "requirement_ids": ["R1"], "given": "amount 100000", "when": "tính phí",
                     "then": "phí 1100"},
                    {"id": "AC2", "requirement_ids": ["R2"], "given": "amount -1", "when": "tính phí",
                     "then": "ValueError"}],
                "risks": [], "open_questions": [], "resolutions": resolutions}
    if stage == "techspec":
        return {"summary": "Synthetic techspec.", "approach": "Sửa fees.py.",
                "components": [{"name": "fees", "change": "Viết transfer_fee", "files": ["fees.py"]}],
                "data_changes": [], "api_changes": [], "invariants": ["Phí không âm"],
                "failure_modes": [{"case": "amount < 0", "handling": "ValueError"}],
                "test_plan": [{"id": "T1", "covers": criteria, "level": "unit", "description": "test_fees.py"}],
                "tasks": [{"id": "K1", "title": "Viết transfer_fee", "description": "Theo PRD.", "files": ["fees.py"]}],
                "rollout": [], "open_questions": [], "resolutions": resolutions}
    if stage == "uxspec":
        return {"summary": "Synthetic UX spec.", "users": ["Merchant"],
                "journeys": [{"id": "J1", "goal": "Xem phí", "steps": ["Nhập số tiền", "Xem phí"], "covers": criteria}],
                "states": [{"id": "S1", "where": "Ô số tiền", "state": "error", "behaviour": "Báo số tiền âm"}],
                "components": [{"name": "Ô nhập", "reuse": "Dùng ô nhập có sẵn"}],
                "copy": [{"key": "error.negative", "text": "Số tiền phải lớn hơn 0"}],
                "accessibility": ["Ô nhập có nhãn"], "responsive": ["Một cột trên màn hình hẹp"],
                "decisions": [], "open_questions": [], "resolutions": resolutions}
    if stage in {"write-docs", "write-content"}:
        target = Path("docs/fees.md" if stage == "write-docs" else "content/home.md")
        target.parent.mkdir(exist_ok=True)
        target.write_text("# Phí chuyển khoản\n\nPhí 1,1%, làm tròn lên.\n")
        return {"summary": f"Synthetic {stage}.", "changes": [{"file": str(target), "description": "Synthetic."}],
                "tests": [], "commands_run": [], "resolutions": resolutions, "open_questions": []}
    if stage in {"prd-review", "uxspec-review", "techspec-review"}:
        findings = [{"id": "F1", "target": "overall", "severity": "major", "reason": "Synthetic objection.",
                     "suggestion": "Synthetic fix."}] if behavior == "blocking" else []
        return {"summary": "Synthetic document review.", "findings": findings, "limitations": []}
    if stage == "implement":
        changes, tests = [], []
        fees = Path("fees.py")
        code = BUGGY_FEE if behavior == "buggy" else CORRECT_FEE
        if fees.read_text() != code:
            fees.write_text(code)
            changes.append({"file": "fees.py", "description": "Synthetic implementation."})
        if not Path("test_fees_zero.py").exists():
            Path("test_fees_zero.py").write_text(ZERO_TEST)
            tests.append({"file": "test_fees_zero.py", "covers": criteria})
        return {"summary": "Synthetic implementation.", "changes": changes, "tests": tests,
                "commands_run": [{"command": "python -m unittest", "exit_code": 0, "note": "synthetic claim"}],
                "resolutions": resolutions, "open_questions": []}
    if stage in {"code-review", "qa", "docs-review", "content-review", "ui-review"}:
        findings = [{"id": "F1", "severity": "major", "kind": "correctness", "file": "fees.py", "line": 1,
                     "reason": "Synthetic objection.", "suggestion": "Synthetic fix."}] if behavior == "blocking" else []
        return {"summary": "Synthetic code review.", "findings": findings, "limitations": [],
                "acceptance": [{"id": a, "status": "met", "reason": "Synthetic."} for a in context["acceptance_ids"]]}
    raise SystemExit(f"unknown flow stage {stage}")


name = "codex" if sys.argv[1:2] == ["exec"] else "antigravity" if "--input-format" in sys.argv else "claude"
behavior_file = Path(__file__).parent / "behaviors.json"
behaviors = json.loads(behavior_file.read_text()) if behavior_file.exists() else {}
stdin = sys.stdin.read()
if "--input-format" in sys.argv:
    packet = json.loads(stdin)["message"]["content"]
else:
    packet = stdin
flow_match = re.search(r"^FLOW_STAGE: ([\w-]+)\nFLOW_JOB: (\S+)$", packet, re.M)
stage_match = re.search(r"^LAB_STAGE: (\w+)$", packet, re.M)
stage = flow_match.group(1) if flow_match else stage_match.group(1) if stage_match else "research"
# Research jobs run in jobs/<job>/<worker>; flow jobs run in the repository worktree.
job = flow_match.group(2) if flow_match else Path.cwd().parent.name
behavior = behaviors.get(job, behaviors.get(name, "success"))
context = json.loads(packet.split("<<<CONTEXT\n", 1)[1].split("\nCONTEXT>>>", 1)[0]) if "<<<CONTEXT\n" in packet else {}
if behavior_file.exists():
    fd = os.open(Path(__file__).parent / "calls.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.write(fd, (json.dumps({"job": job, "worker": name, "stage": stage,
                              "path_hint": "absolute paths only" in stdin}) + "\n").encode())
    os.close(fd)
report = {
    "summary": "Accept only completed, schema-valid results.",
    "claims": [{"id": "C01", "text": "All acceptance gates must pass.", "source_ids": ["S01"]}],
    "limitations": ["Synthetic process fixture; no provider involved."],
}
evidence = [{"source_id": "S01", "excerpt": "A worker result is accepted only if"}]
if stage in {"audit", "adjudication"}:
    targets = ["summary", *[c["id"] for c in context["report"]["claims"]], "limitations"]
    report = {"summary": "Synthetic source audit.", "items": [
        {"target": target, "verdict": "supported" if target != "limitations" else "unverified",
         "reason": "Synthetic fixture verdict.", "evidence": evidence if target != "limitations" else []}
        for target in targets], "limitations": ["Synthetic audit, not semantic verification."]}
    if stage == "adjudication":
        report["review_resolutions"] = [{"finding_id": f["id"], "disposition": "unresolved",
                                         "reason": "Synthetic unresolved objection.", "evidence": []}
                                        for f in context["review"]["findings"]]
    if behavior == "forged_quote":
        report["items"][0]["evidence"][0]["excerpt"] = "This quotation was invented."
    if behavior == "missing_target":
        report["items"].pop()
elif stage == "review":
    report = {"summary": "Synthetic review.", "checked_targets": ["summary", *[
        c["id"] for c in context["report"]["claims"]], "limitations"], "findings": [], "limitations": ["Synthetic review."]}
    if behavior == "unresolved_finding":
        report["findings"] = [{"id": "F01", "target": "C01", "kind": "interpretation", "severity": "major",
                                "reason": "Synthetic substantive objection.", "evidence": evidence,
                                "resolution": "Independent policy decision needed."}]
elif stage == "synthesis":
    report = {"summary": "Synthetic final synthesis.", "recommendations": [{"text": "Inspect the evidence.",
               "claim_refs": context["claim_refs"][:1]}], "limitations": ["Offline fixture only."]}
elif flow_match:
    report = flow_report(stage, context, behavior)
if behavior in {"sleep", "child", "exited_parent"}:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path("child.pid").write_text(str(child.pid))
    if behavior != "exited_parent":
        time.sleep(60)
if behavior == "output_limit":
    print("x" * 200_000, flush=True)
    time.sleep(60)
if behavior == "nonzero":
    sys.exit(3)
if behavior == "malformed_json":
    print("not json")
    sys.exit(0)
if behavior == "bad_schema":
    report["summary"] = 42
if behavior == "unknown_source":
    report["claims"][0]["source_ids"] = ["S99"]
if behavior == "empty_source":
    report["claims"][0]["source_ids"] = []
if behavior == "duplicate_claim":
    report["claims"] *= 2
if behavior == "empty_claims":
    report["claims"] = []
if behavior == "empty_summary":
    report["summary"] = "  "
if behavior == "blank_claim":
    report["claims"][0]["text"] = " "
if behavior == "stderr_denial":
    print("tool permission denied", file=sys.stderr)

if name == "codex":
    destination = Path(sys.argv[sys.argv.index("-o") + 1])
    destination.write_text(json.dumps(report))
    if behavior == "provider_failure":
        print(json.dumps({"type": "turn.failed", "error": {"message": "synthetic failure"}}))
    elif behavior != "missing_completion":
        print(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 10}}))
else:
    envelope = {"structured_output": report, "usage": {"output_tokens": 10}}
    if name == "claude":
        envelope.update({"subtype": "success", "is_error": False})
        if behavior == "provider_failure":
            envelope["is_error"] = True
    else:
        envelope["status"] = "ERROR" if behavior in {"provider_failure", "hang_after_result_error"} else "SUCCESS"
    if behavior == "missing_structured":
        del envelope["structured_output"]
    if behavior == "provider_timeout":
        # Some CLI versions return SUCCESS plus partial data on print timeout.
        envelope["finished_reason"] = "print_timeout"
    if behavior == "structured_denial":
        envelope["permission_denials"] = [{"tool_name": "Read", "tool_use_id": "synthetic"}]
    print(json.dumps({"event": "result", "result": envelope} if name == "antigravity" else envelope), flush=True)
    if behavior in {"hang_after_result", "hang_after_result_error"}:
        # Seen with agy: the final result event is written, then the process never exits.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path("child.pid").write_text(str(child.pid))
        time.sleep(60)
