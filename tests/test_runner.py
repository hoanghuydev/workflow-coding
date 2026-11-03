import asyncio
import copy
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab import runtime as run_lab


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("config", "inputs", "runs", "fake"):
            (self.root / folder).mkdir()
        for relative in ("config/report.schema.json", "config/agy-research.json", "inputs/brief.md"):
            shutil.copyfile(run_lab.ROOT / relative, self.root / relative)
        self.schema = run_lab.read_json(self.root / "config/report.schema.json")
        self.fake = self.root / "fake/fake_cli.py"
        shutil.copyfile(Path(__file__).with_name("fake_cli.py"), self.fake)
        self.config = {
            name: {"prefix": [sys.executable, str(self.fake)], "model": "synthetic-model", "effort": None}
            for name in ("codex", "claude", "antigravity")
        }
        run_lab.write_json(self.root / "config/agents.local.json", self.config)
        self.set_behaviors({})

    def set_behaviors(self, behaviors):
        run_lab.write_json(self.fake.parent / "behaviors.json", behaviors)

    def new_run(self):
        run_dir = self.root / "runs" / str(len(list((self.root / "runs").iterdir())))
        run_dir.mkdir()
        shutil.copyfile(self.root / "inputs/brief.md", run_dir / "brief.snapshot.md")
        shutil.copyfile(self.root / "config/agy-research.json", run_dir / "agy-policy.snapshot.json")
        run_lab.write_json(run_dir / "schema.snapshot.json", self.schema)
        return run_dir

    async def run_worker(self, name, behavior="success"):
        self.set_behaviors({name: behavior})
        directory = self.new_run()
        row = await run_lab.worker(name, self.config[name], directory, self.schema)
        self.assertEqual(row, run_lab.read_json(directory / name / "manifest.json"))
        return row, directory

    def assert_not_running(self, pid):
        status = Path(f"/proc/{pid}/stat")
        if status.exists():
            self.assertEqual(status.read_text().split(") ", 1)[1].split()[0], "Z")

    async def test_success_parsers_hashes_and_cost_unknown(self):
        for name in self.config:
            with self.subTest(name=name):
                row, directory = await self.run_worker(name)
                self.assertEqual(row["status"], "collected_unverified")
                self.assertIsNone(row["cost_usd"])
                self.assertIsNone(row["effective_model"])
                self.assertEqual(row["input_sha256"], run_lab.digest(directory / "brief.snapshot.md"))
                self.assertEqual(row["report_sha256"], run_lab.digest(directory / name / "report.json"))

    async def test_failed_outputs_are_not_accepted(self):
        for name in self.config:
            cases = ["nonzero", "provider_failure", "malformed_json", "bad_schema", "unknown_source",
                     "empty_source", "duplicate_claim", "empty_claims", "empty_summary", "blank_claim", "stderr_denial"]
            cases += ["missing_completion"] if name == "codex" else ["missing_structured", "structured_denial"]
            for behavior in cases:
                with self.subTest(name=name, behavior=behavior):
                    row, directory = await self.run_worker(name, behavior)
                    self.assertEqual(row["status"], "failed")
                    self.assertIn("error", row)
                    self.assertFalse((directory / name / "report.json").exists())
                    self.assertTrue((directory / name / "stdout.log").is_file())

    async def test_timeout_kills_child(self):
        with patch.object(run_lab, "TIMEOUT", 0.3):
            row, directory = await self.run_worker("codex", "child")
        self.assertEqual(row["error"], "timeout")
        self.assert_not_running(int((directory / "codex/child.pid").read_text()))

    async def test_provider_print_timeout_is_not_accepted_even_with_valid_report(self):
        row, directory = await self.run_worker("antigravity", "provider_timeout")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "provider_print_timeout")
        self.assertEqual(row["provider_finished_reason"], "print_timeout")
        self.assertFalse((directory / "antigravity/report.json").exists())

    async def test_cleanup_after_parent_exit_kills_child(self):
        row, directory = await self.run_worker("codex", "exited_parent")
        self.assertEqual(row["status"], "collected_unverified")
        await asyncio.sleep(0.05)
        self.assert_not_running(int((directory / "codex/child.pid").read_text()))

    async def test_output_limit_stops_worker(self):
        with patch.object(run_lab, "MAX_OUTPUT", 64_000):
            row, _ = await self.run_worker("codex", "output_limit")
        self.assertEqual(row["error"], "output_limit")

    async def test_cancellation_saves_manifest_and_kills_child(self):
        self.set_behaviors({"codex": "child"})
        directory = self.new_run()
        task = asyncio.create_task(run_lab.worker("codex", self.config["codex"], directory, self.schema))
        for _ in range(100):
            if (directory / "codex/child.pid").exists():
                break
            await asyncio.sleep(0.02)
        self.assertTrue((directory / "codex/child.pid").exists())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(run_lab.read_json(directory / "codex/manifest.json")["status"], "interrupted")
        self.assert_not_running(int((directory / "codex/child.pid").read_text()))

    async def test_batch_keeps_successes_and_records_sqlite(self):
        self.set_behaviors({"claude": "nonzero"})
        with patch.object(run_lab, "ROOT", self.root):
            code = await run_lab.main()
        self.assertEqual(code, 1)
        results = list((self.root / "runs").glob("*/results.json"))
        self.assertEqual(len(results), 1)
        rows = run_lab.read_json(results[0])
        self.assertEqual([r["status"] for r in rows], ["collected_unverified", "failed", "collected_unverified"])
        with closing(sqlite3.connect(self.root / "runs/state.db")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 3)

    async def test_policy_and_brief_are_locked_before_version_checks(self):
        expected_policy = run_lab.read_json(self.root / "config/agy-research.json")
        expected_brief = (self.root / "inputs/brief.md").read_bytes()
        execute = subprocess.run

        def mutate_after_preflight(*args, **kwargs):
            run_lab.write_json(self.root / "config/agy-research.json", {
                "permissions": {"deny": [], "allow": ["command(*)"], "ask": []}})
            (self.root / "inputs/brief.md").write_text("Changed after preflight")
            return execute(*args, **kwargs)

        with patch.object(run_lab, "ROOT", self.root), patch.object(run_lab.subprocess, "run", side_effect=mutate_after_preflight):
            self.assertEqual(await run_lab.main(), 0)
        directory = next((self.root / "runs").glob("*/results.json")).parent
        self.assertEqual(run_lab.read_json(directory / "agy-policy.snapshot.json"), expected_policy)
        self.assertEqual((directory / "brief.snapshot.md").read_bytes(), expected_brief)

    async def test_preflight_rejects_invalid_configuration_and_policy(self):
        with patch.object(run_lab, "ROOT", self.root):
            run_lab.preflight()
            for change in ({"model": "REPLACE_MODEL"}, {"effort": "invented"}, {"prefix": ["/missing"]}):
                config = copy.deepcopy(self.config)
                config["codex"].update(change)
                run_lab.write_json(self.root / "config/agents.local.json", config)
                with self.assertRaises(ValueError):
                    run_lab.preflight()
            run_lab.write_json(self.root / "config/agents.local.json", self.config)
            policy = run_lab.read_json(self.root / "config/agy-research.json")
            policy["permissions"]["deny"].remove("command(*)")
            run_lab.write_json(self.root / "config/agy-research.json", policy)
            with self.assertRaises(ValueError):
                run_lab.preflight()


if __name__ == "__main__":
    unittest.main()
