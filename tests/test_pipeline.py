import asyncio
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab import contracts, pipeline, runtime
from lab.state import State, process_group_alive, run_lock


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("config", "inputs", "runs", "fake", "protocols", ".agents/skills"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for relative in ("config/report.schema.json", "config/agy-research.json", "config/review-rubric.md", "inputs/brief.md"):
            shutil.copyfile(runtime.ROOT / relative, self.root / relative)
        shutil.copytree(runtime.ROOT / "protocols", self.root / "protocols", dirs_exist_ok=True)
        shutil.copytree(runtime.ROOT / ".agents/skills/multi-reviewer-patterns",
                        self.root / ".agents/skills/multi-reviewer-patterns")
        lock = runtime.read_json(runtime.ROOT / "config/skills.lock.json")
        lock["skills"] = [s for s in lock["skills"] if s["name"] == "multi-reviewer-patterns"]
        runtime.write_json(self.root / "config/skills.lock.json", lock)
        self.fake = self.root / "fake/fake_cli.py"
        shutil.copyfile(Path(__file__).with_name("fake_cli.py"), self.fake)
        cfg = {worker: {"prefix": [sys.executable, str(self.fake)], "model": "synthetic-model", "effort": None}
               for worker in pipeline.WORKERS}
        runtime.write_json(self.root / "config/agents.local.json", cfg)
        self.behaviors({})

    def behaviors(self, values):
        runtime.write_json(self.fake.parent / "behaviors.json", values)

    def prepare(self, **kwargs):
        return pipeline.prepare(self.root, "inputs/brief.md", timeout=5, **kwargs)

    def run_dir(self):
        return next((self.root / "runs").iterdir())

    def calls(self):
        path = self.fake.parent / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def test_complete_pipeline_blind_packets_and_resume_without_inference(self):
        self.assertEqual(await pipeline.run(self.root, self.prepare()), 0)
        directory = self.run_dir()
        summary = runtime.read_json(directory / "summary.json")
        self.assertEqual(summary["model_calls_started"], 13)
        self.assertEqual(len(self.calls()), 13)
        self.assertIsNone(summary["cost_usd"])
        self.assertIsNone(summary["known_cost_usd"])
        self.assertEqual(summary["status"], "complete")
        verification = runtime.read_json(directory / "verification.json")
        self.assertFalse(verification["human_reviewed"])
        for item in verification["items"]:
            self.assertIn("report_sha256", item)
            if item["status"] == "verified":
                self.assertTrue(item["source_hashes"])
        for alias, author in pipeline.ALIASES.items():
            self.assertNotEqual(pipeline.AUDITORS[alias], author)
            self.assertNotEqual(pipeline.REVIEWERS[alias], author)
            self.assertNotEqual(pipeline.AUDITORS[alias], pipeline.REVIEWERS[alias])
            packet = (directory / "jobs" / f"review-{alias}" / pipeline.REVIEWERS[alias] / "INPUT.md").read_text()
            context = json.loads(packet.split("<<<CONTEXT\n")[1].split("\nCONTEXT>>>")[0])
            self.assertEqual(set(context), {"report_alias", "report"})
            self.assertNotIn(author, json.dumps(context))
            self.assertIn("Multi-Reviewer Patterns", packet)
        self.assertEqual(await pipeline.run(self.root, resume=directory), 0)
        self.assertEqual(len(self.calls()), 13)

    async def test_failed_audit_keeps_other_results_and_explicit_retry_preserves_attempt(self):
        self.behaviors({"audit-A": "nonzero"})
        self.assertEqual(await pipeline.run(self.root, self.prepare()), 1)
        directory = self.run_dir()
        self.assertTrue((directory / "jobs/research-A/codex/report.json").exists())
        self.assertTrue((directory / "jobs/adjudication-B/claude/report.json").exists())
        self.assertFalse((directory / "jobs/synthesis-final").exists())
        count = len(self.calls())
        self.behaviors({})
        self.assertEqual(await pipeline.run(self.root, resume=directory), 1)
        self.assertEqual(len(self.calls()), count)
        self.assertEqual(await pipeline.run(self.root, resume=directory, retry_failed=True, max_calls=14), 0)
        self.assertEqual(len(self.calls()), 14)
        self.assertEqual(len(list((directory / "attempts").iterdir())), 1)
        self.assertEqual(runtime.read_json(directory / "summary.json")["model_calls_started"], 14)

    async def test_call_limit_is_durable_and_pending_jobs_can_resume(self):
        self.assertEqual(await pipeline.run(self.root, self.prepare(max_calls=2)), 1)
        directory = self.run_dir()
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(await pipeline.run(self.root, resume=directory, max_calls=13), 0)
        self.assertEqual(len(self.calls()), 13)

    async def test_forged_source_excerpt_and_missing_coverage_are_rejected(self):
        self.behaviors({"audit-A": "forged_quote", "audit-B": "missing_target"})
        self.assertEqual(await pipeline.run(self.root, self.prepare()), 1)
        directory = self.run_dir()
        for alias, worker in (("A", "claude"), ("B", "antigravity")):
            manifest = runtime.read_json(directory / "jobs" / f"audit-{alias}" / worker / "manifest.json")
            self.assertEqual(manifest["status"], "failed")
        items = runtime.read_json(directory / "verification.json")["items"]
        self.assertTrue(all(i["status"] == "inconclusive" for i in items if i["ref"].startswith(("A/", "B/"))))

    async def test_unresolved_review_stays_disputed_despite_supported_adjudication(self):
        self.behaviors({"review-A": "unresolved_finding"})
        self.assertEqual(await pipeline.run(self.root, self.prepare()), 0)
        items = runtime.read_json(self.run_dir() / "verification.json")["items"]
        claim = next(i for i in items if i["ref"] == "A/C01")
        self.assertEqual(claim["status"], "disputed")
        self.assertEqual(claim["unresolved"], ["F01"])

    async def test_completed_manifest_recovers_after_state_commit_was_interrupted(self):
        self.assertEqual(await pipeline.run(self.root, self.prepare()), 0)
        directory = self.run_dir()
        with sqlite3.connect(directory / "state.db") as db:
            db.execute("UPDATE jobs SET status='running', metadata='{}' WHERE id='research-A'")
        self.assertEqual(await pipeline.run(self.root, resume=directory), 0)
        self.assertEqual(len(self.calls()), 13)

    async def test_revalidate_saved_output_recovers_without_repeating_paid_calls(self):
        with patch.object(contracts, "check_evidence", side_effect=ValueError("previous validator rejected output")):
            self.assertEqual(await pipeline.run(self.root, self.prepare()), 1)
        directory = self.run_dir()
        initial_calls = self.calls()
        self.assertEqual(sum(c["stage"] == "audit" for c in initial_calls), 3)
        original_raw = (directory / "jobs/audit-A/claude/stdout.log").read_bytes()
        self.assertEqual(await pipeline.run(self.root, resume=directory, revalidate=True), 0)
        self.assertEqual(len(self.calls()), 13)
        self.assertEqual(sum(c["stage"] == "audit" for c in self.calls()), 3)
        self.assertEqual((directory / "jobs/audit-A/claude/stdout.log").read_bytes(), original_raw)
        self.assertEqual(len(list((directory / "revalidations").iterdir())), 3)

    async def test_tampered_report_is_rejected_without_new_call(self):
        self.assertEqual(await pipeline.run(self.root, self.prepare()), 0)
        directory = self.run_dir()
        (directory / "jobs/research-A/codex/report.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            await pipeline.run(self.root, resume=directory)
        self.assertEqual(len(self.calls()), 13)

    async def test_cancel_records_interruption_and_kills_process_group(self):
        self.behaviors({"research-A": "child"})
        task = asyncio.create_task(pipeline.run(self.root, self.prepare()))
        child_files = []
        for _ in range(150):
            child_files = list((self.root / "runs").glob("*/jobs/research-A/codex/child.pid"))
            if child_files:
                break
            await asyncio.sleep(0.02)
        self.assertTrue(child_files)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        directory = self.run_dir()
        state = State(directory)
        try:
            row = state.get("research-A")
            self.assertEqual(row["status"], "interrupted")
            self.assertFalse(process_group_alive(row["metadata"]["pid"]))
        finally:
            state.close()

    async def test_resume_refuses_retry_while_old_process_group_is_alive(self):
        prepared = self.prepare()
        directory = self.root / "runs/interrupted"
        pipeline.seal(directory, prepared, await pipeline.versions(prepared["config"]))
        old = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)",
                                                    start_new_session=True)
        state = State(directory)
        state.plan("research-A", "research", "codex")
        state.start("research-A", 13)
        state.save("research-A", {"status": "running", "pid": old.pid})
        state.close()
        try:
            self.assertEqual(await pipeline.run(self.root, resume=directory, retry_failed=True), 1)
            self.assertFalse(any(call["job"] == "research-A" for call in self.calls()))
            self.assertTrue(process_group_alive(old.pid))
            gaps = runtime.read_json(directory / "verification.json")["coverage_gaps"]
            self.assertTrue(any("still active" in gap for gap in gaps))
        finally:
            old.kill()
            await old.wait()

    def test_locks_source_ids_and_installed_skill_integrity(self):
        with run_lock(self.root):
            with self.assertRaisesRegex(ValueError, "Another supervisor"):
                with run_lock(self.root):
                    pass
        with self.assertRaisesRegex(ValueError, "Duplicate source"):
            contracts.extract_sources("Source S01 first\nSource S01 second")
        skill = self.root / ".agents/skills/multi-reviewer-patterns/SKILL.md"
        skill.write_text("changed")
        with self.assertRaisesRegex(ValueError, "differs from lock"):
            self.prepare()

    def test_quote_normalization_changes_only_whitespace_and_stores_original_span(self):
        source = "A worker result is accepted only if process exit status, provider completion\nstatus, and the required output schema all pass."
        quote = {"source_id": "S01", "excerpt": source.replace("\n", " ")}
        contracts.check_evidence([quote], {"S01": source}, required=True)
        self.assertEqual(quote["excerpt"], source)
        with self.assertRaisesRegex(ValueError, "absent"):
            contracts.check_evidence([{"source_id": "S01", "excerpt": source.replace("only if", "if and only if")}],
                                     {"S01": source}, required=True)


if __name__ == "__main__":
    unittest.main()
