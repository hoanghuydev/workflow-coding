"""Offline tests for hooks/stop_audit.py and the worker flag; no real CLI is called."""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from lab import runtime as run_lab

HOOK = Path(__file__).resolve().parents[1] / "hooks/stop_audit.py"
spec = importlib.util.spec_from_file_location("stop_audit", HOOK)
stop_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stop_audit)

# Stands in for `claude -p` and `codex exec`: reports what it saw instead of judging.
FAKE_AUDITOR = textwrap.dedent("""\
    import json, os, sys
    from pathlib import Path
    prompt = sys.stdin.read()
    seen = {"worker_flag": os.environ.get("SEPAY_LAB_WORKER"), "argv": sys.argv[1:],
            "transcript": Path("transcript.jsonl").read_text(encoding="utf-8"),
            "context": json.loads(prompt[prompt.rindex("\\n\\n{") + 2:])}
    verdict = {"ok": False, "reason": json.dumps(seen)}
    if "exec" in sys.argv:
        Path(sys.argv[sys.argv.index("-o") + 1]).write_text(json.dumps(verdict), encoding="utf-8")
    else:
        print(json.dumps({"subtype": "success", "is_error": False, "structured_output": verdict}))
    """)

# Starts a grandchild (like the Node wrapper starting native codex), then hangs.
SLOW_AUDITOR = textwrap.dedent("""\
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(sys.argv[1], "w").write(str(child.pid))
    time.sleep(60)
    """)


class StopAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        state = patch.object(stop_audit, "STATE", self.temp / "state")
        state.start()
        self.addCleanup(state.stop)
        self.calls = []

    def audit(self, verdict):
        def fake(runtime, turn):
            self.calls.append((runtime, turn))
            if isinstance(verdict, Exception):
                raise verdict
            return verdict
        return fake

    def run_hook(self, runtime, payload, verdict=None, environ=None):
        out = io.StringIO()
        code = stop_audit.main([runtime], io.StringIO(json.dumps(payload)), out,
                               environ or {}, self.audit(verdict or {"ok": True, "reason": "fine"}))
        self.assertEqual(code, 0)
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def payload(self, runtime, **extra):
        if runtime == "agy":
            return {"conversationId": "c1", "lastUserInput": "hi", "transcriptPath": "/t.jsonl",
                    "terminationReason": "NO_TOOL_CALL", "executionNum": 0, "fullyIdle": True, **extra}
        return {"session_id": "s1", "transcript_path": "/t.jsonl", "stop_hook_active": False,
                "last_assistant_message": "done", **extra}

    def test_routes_each_operator_to_the_other_provider(self):
        self.assertEqual(stop_audit.AUDITOR, {"claude": "codex", "codex": "claude", "agy": "claude"})
        self.assertEqual(stop_audit.MODELS["claude"], ("claude-opus-5-5", "medium"))

    def test_workers_and_switch_are_never_audited(self):
        for runtime in stop_audit.AUDITOR:
            for environ in ({"SEPAY_LAB_WORKER": "1"}, {"SEPAY_LAB_STOP_AUDIT": "off"}):
                with self.subTest(runtime=runtime, environ=environ):
                    result = self.run_hook(runtime, self.payload(runtime), {"ok": False, "reason": "x"}, environ)
                    self.assertEqual(result, {"decision": "stop"} if runtime == "agy" else None)
        self.assertEqual(self.calls, [])

    def test_ok_verdict_lets_operator_stop(self):
        self.assertIsNone(self.run_hook("claude", self.payload("claude")))
        self.assertIsNone(self.run_hook("codex", self.payload("codex")))
        self.assertEqual(self.run_hook("agy", self.payload("agy")), {"decision": "stop"})
        self.assertEqual([c[0] for c in self.calls], ["claude", "codex", "agy"])

    def test_findings_block_in_each_cli_format(self):
        verdict = {"ok": False, "reason": "E29 | 'tests passed' | no test output"}
        for runtime, decision in (("claude", "block"), ("codex", "block"), ("agy", "continue")):
            with self.subTest(runtime=runtime):
                result = self.run_hook(runtime, self.payload(runtime), verdict)
                self.assertEqual(result["decision"], decision)
                self.assertIn("E29 | 'tests passed'", result["reason"])
                self.assertIn("not from the user", result["reason"])

    def test_a_continued_turn_is_not_audited_again(self):
        flagged = {"ok": False, "reason": "x"}
        self.assertIsNone(self.run_hook("claude", self.payload("claude", stop_hook_active=True), flagged))
        self.assertIsNone(self.run_hook("codex", self.payload("codex", stop_hook_active=True), flagged))
        # agy counts continuations within a user message: 0 first, 1 after a "continue".
        self.assertEqual(self.run_hook("agy", self.payload("agy", executionNum=1), flagged), {"decision": "stop"})
        self.assertEqual(self.calls, [])
        # A repeated user message starts again at executionNum 0, so it is audited.
        self.assertEqual(self.run_hook("agy", self.payload("agy"), flagged)["decision"], "continue")

    def test_agy_stop_after_error_or_cancel_is_not_audited(self):
        self.assertEqual(self.run_hook("agy", self.payload("agy", terminationReason="USER_CANCELED")),
                         {"decision": "stop"})
        self.assertEqual(self.calls, [])

    def test_auditor_failure_is_reported_once_per_session(self):
        first = self.run_hook("codex", self.payload("codex"), RuntimeError("quota"))
        self.assertEqual(first["decision"], "block")
        self.assertIn("not independently audited", first["reason"])
        self.assertIn("quota", first["reason"])
        self.assertIsNone(self.run_hook("codex", self.payload("codex"), RuntimeError("quota")))
        # Another session is told; a working audit re-arms the notice for this one.
        self.assertEqual(self.run_hook("codex", self.payload("codex", session_id="s2"), RuntimeError("x"))["decision"],
                         "block")
        self.assertIsNone(self.run_hook("codex", self.payload("codex")))
        self.assertEqual(self.run_hook("codex", self.payload("codex"), RuntimeError("again"))["decision"], "block")
        log = (stop_audit.STATE / "audit.log").read_text(encoding="utf-8")
        self.assertIn('"outcome": "error_repeat"', log)

    def test_unreadable_payload_never_blocks(self):
        for runtime in stop_audit.AUDITOR:
            out = io.StringIO()
            stop_audit.main([runtime], io.StringIO("not json"), out, {}, self.audit({"ok": False, "reason": "x"}))
            self.assertEqual(out.getvalue().strip(), '{"decision": "stop"}' if runtime == "agy" else "")
        stop_audit.main(["unknown"], io.StringIO("{}"), io.StringIO(), {}, self.audit(None))
        self.assertEqual(self.calls, [])

    def test_log_holds_no_reason_text_and_state_is_private(self):
        self.run_hook("claude", self.payload("claude"), {"ok": False, "reason": "SECRET-QUOTE"})
        log = (stop_audit.STATE / "audit.log").read_text(encoding="utf-8")
        self.assertIn('"outcome": "block"', log)
        self.assertNotIn("SECRET-QUOTE", log)
        self.assertEqual(stat.S_IMODE(stop_audit.STATE.stat().st_mode), 0o700)

    def test_run_audit_uses_a_flagged_isolated_auditor_on_a_transcript_copy(self):
        fake = self.temp / "fake_auditor.py"
        fake.write_text(FAKE_AUDITOR, encoding="utf-8")
        transcript = self.temp / "session.jsonl"
        transcript.write_text('{"role": "user", "text": "hi"}\n', encoding="utf-8")
        turn = {"transcript": str(transcript), "last_assistant_message": "done", "last_user_input": None,
                "background_running": True}
        with patch.object(stop_audit, "cli_prefix", lambda name: [sys.executable, str(fake)]):
            for runtime, expect in (("claude", "exec"), ("codex", "-p"), ("agy", "-p")):
                with self.subTest(runtime=runtime):
                    seen = json.loads(stop_audit.run_audit(runtime, turn)["reason"])
                    self.assertEqual(seen["worker_flag"], "1")
                    self.assertEqual(seen["argv"][0], expect)
                    self.assertEqual(seen["transcript"], transcript.read_text(encoding="utf-8"))
                    self.assertEqual(seen["context"]["operator_runtime"], runtime)
                    self.assertTrue(seen["context"]["background_tasks_still_running"])
                    if expect == "exec":
                        self.assertIn("read-only", seen["argv"])
                        self.assertIn("gpt-6.1-sol", seen["argv"])
                    else:
                        self.assertIn("--restricted", seen["argv"])
                        self.assertEqual(seen["argv"][seen["argv"].index("--setting-sources") + 1], "")
                        self.assertIn("claude-opus-5-5", seen["argv"])
            # A long reply keeps its end, where the closing claims usually are.
            long_turn = {**turn, "last_assistant_message": "x" * 30000 + "CLAIM-AT-END"}
            seen = json.loads(stop_audit.run_audit("codex", long_turn)["reason"])
            sent = seen["context"]["last_assistant_message"]
            self.assertTrue(sent.endswith("CLAIM-AT-END"))
            self.assertIn("characters omitted", sent)
        # The private copy is removed after each audit.
        self.assertEqual([p.name for p in stop_audit.STATE.iterdir()], [])

    def test_missing_transcript_is_an_error(self):
        for path in (str(self.temp / "none.jsonl"), None):
            with self.subTest(path=path), self.assertRaises(FileNotFoundError):
                stop_audit.run_audit("codex", {"transcript": path, "last_assistant_message": None,
                                               "last_user_input": None, "background_running": False})

    @unittest.skipIf(os.name == "nt", "process groups are POSIX")
    def test_timeout_kills_the_whole_auditor_process_tree(self):
        slow = self.temp / "slow_auditor.py"
        slow.write_text(SLOW_AUDITOR, encoding="utf-8")
        pid_file = self.temp / "grandchild.pid"
        with patch.object(stop_audit, "AUDIT_TIMEOUT", 2), self.assertRaises(Exception):
            stop_audit.run_command([sys.executable, str(slow), str(pid_file)], "", self.temp)
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("auditor grandchild survived the timeout")


class WorkerFlagTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_worker_cli_gets_the_flag(self):
        seen = {}

        async def capture(*args, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop before running")

        with tempfile.TemporaryDirectory() as temp, \
                patch.object(run_lab.asyncio, "create_subprocess_exec", capture):
            run_dir = Path(temp)
            (run_dir / "brief.snapshot.md").write_text("brief", encoding="utf-8")
            cfg = {"prefix": [sys.executable], "model": "m", "effort": None}
            row = await run_lab.worker("claude", cfg, run_dir, {"type": "object"})
        self.assertEqual(row["status"], "failed")
        self.assertEqual(seen["env"]["SEPAY_LAB_WORKER"], "1")


if __name__ == "__main__":
    unittest.main()
