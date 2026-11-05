import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from langgraph.types import Command

from lab import pipeline, runtime
from lab.flow import task as flow_task, workspace
from lab.flow.config import check_roster
import run_flow


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in ("config/flow.json", "config/personas.json", "config/agy-research.json",
                         "config/report.schema.json", "config/review-rubric.md", "inputs/brief.md"):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(runtime.ROOT / relative, self.root / relative)
        shutil.copytree(runtime.ROOT / "protocols", self.root / "protocols")
        flow = runtime.read_json(runtime.ROOT / "config/flow.json")
        skills = {"multi-reviewer-patterns", *(name for names in flow["skills"].values() for name in names)}
        for name in skills:
            shutil.copytree(runtime.ROOT / ".agents/skills" / name, self.root / ".agents/skills" / name)
        lock = runtime.read_json(runtime.ROOT / "config/skills.lock.json")
        lock["skills"] = [s for s in lock["skills"] if s["name"] in skills]
        runtime.write_json(self.root / "config/skills.lock.json", lock)
        (self.root / "tests").mkdir()
        shutil.copyfile(Path(__file__).with_name("fake_cli.py"), self.root / "tests/fake_cli.py")
        self.behaviors({})
        self.task = None

    def behaviors(self, values):
        runtime.write_json(self.root / "tests/behaviors.json", values)

    def calls(self):
        path = self.root / "tests/calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def jobs(self):
        return [call["job"] for call in self.calls()]

    async def start(self, **kwargs):
        directory = await flow_task.create(self.root, demo=True, **kwargs)
        self.task = flow_task.load(self.root, directory)
        self.addCleanup(self.task.close)
        return await flow_task.advance(self.task, flow_task.initial_input(self.task))

    async def decide(self, **decision):
        return await flow_task.advance(self.task, Command(resume=decision))

    @staticmethod
    def gate(snapshot):
        return snapshot.interrupts[0].value["kind"] if snapshot.interrupts else None

    def packet_context(self, job, worker):
        packet = (self.task.directory / "jobs" / job / worker / "INPUT.md").read_text()
        return json.loads(packet.split("<<<CONTEXT\n")[1].split("\nCONTEXT>>>")[0])

    async def test_p2_flow_gates_commit_tests_and_finish_without_merge(self):
        snapshot = await self.start()
        self.assertEqual(self.gate(snapshot), "techspec")  # P2 has no PRD gate
        self.assertEqual(self.jobs(), ["triage", "prd-draft-1", "prd-review-requirements-reviewer-1",
                                       "techspec-draft-1", "techspec-review-architecture-reviewer-1"])
        snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "release")
        values = snapshot.values
        self.assertEqual(values["tests"]["status"], "passed")
        worktree = self.task.worktree
        self.assertEqual(workspace.head(worktree), values["implementation"]["head"])
        self.assertIn("Flow-Job: implement-1", workspace.git(worktree, "log", "-1", "--format=%B"))
        self.assertEqual(sorted(values["implementation"]["changed_files"]), ["fees.py", "test_fees_zero.py"])
        # The base repository branch is untouched: the flow never merges.
        repo = Path(self.task.settings["repo"])
        self.assertEqual(workspace.head(repo), self.task.settings["base_sha"])
        # Reviewer runtime differs from the implementer and sees claims labelled as claims.
        self.assertTrue((self.task.directory / "jobs/code-review-code-reviewer-1/claude/INPUT.md").exists())
        context = self.packet_context("code-review-code-reviewer-1", "claude")
        self.assertIn("implementation_claims", context)
        self.assertEqual(context["tests"]["status"], "passed")
        snapshot = await self.decide(action="approve", note="ok")
        self.assertEqual(snapshot.values["status"], "approved")
        self.assertFalse(snapshot.next)
        self.assertTrue((self.task.directory / "report.md").is_file())
        calls = len(self.calls())
        self.assertEqual(calls, 7)
        self.assertEqual(self.task.state.calls(), 7)
        await flow_task.advance(self.task, None)  # finished graph: no further inference
        self.assertEqual(len(self.calls()), calls)

    async def test_human_revise_becomes_a_finding_the_author_must_resolve(self):
        snapshot = await self.start()
        snapshot = await self.decide(action="revise", note="Thêm failure mode cho số tiền quá lớn")
        self.assertEqual(self.gate(snapshot), "techspec")
        self.assertEqual(snapshot.values["techspec_round"], 2)
        context = self.packet_context("techspec-draft-2", "codex")
        human = [f for f in context["findings_to_resolve"] if f["source"] == "human"]
        self.assertEqual(len(human), 1)
        self.assertIn("quá lớn", human[0]["reason"])
        self.assertEqual([r["finding_id"] for r in snapshot.values["techspec"]["resolutions"]], [human[0]["id"]])
        self.assertNotIn("techspec", snapshot.values.get("notes", {}))
        self.assertTrue((self.task.directory / "docs/techspec-r2.md").exists())

    async def test_failed_tests_and_blocking_review_drive_fix_rounds(self):
        self.behaviors({"implement-1": "buggy", "code-review-code-reviewer-1": "blocking"})
        snapshot = await self.start()
        snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "release")
        values = snapshot.values
        self.assertEqual(values["impl_round"], 2)
        self.assertEqual(values["tests"]["status"], "passed")
        first = runtime.read_json(self.task.directory / "tests/round-1.json")
        self.assertEqual(first["status"], "failed")
        context = self.packet_context("implement-2", "codex")
        required = {f["id"] for f in context["findings_to_resolve"]}
        self.assertEqual(required, {"code-reviewer/F1", "supervisor/tests"})
        self.assertEqual(len(workspace.log(self.task.worktree, self.task.settings["base_sha"],
                                           values["implementation"]["head"])), 2)

    async def test_fix_rounds_stop_at_the_limit_and_surface_findings_at_release(self):
        self.behaviors({f"code-review-code-reviewer-{n}": "blocking" for n in (1, 2, 3)})  # every review objects
        snapshot = await self.start()
        snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "release")
        self.assertEqual(snapshot.values["impl_round"], 3)  # 1 + max_fix_rounds
        summary = (self.task.directory / snapshot.interrupts[0].value["summary"]).read_text()
        self.assertIn("code-reviewer/F1", summary)

    async def test_timed_out_job_blocks_and_retry_can_raise_the_job_timeout(self):
        self.behaviors({"prd-draft-1": "sleep"})
        snapshot = await self.start(timeout=1)
        self.assertEqual(self.gate(snapshot), "blocked")
        self.assertIn("timeout", " ".join(snapshot.values["blocked"]["reasons"]))
        self.behaviors({})
        seen = []
        original = runtime.worker

        async def spy(*args, **kwargs):
            seen.append(kwargs["timeout"])
            return await original(*args, **kwargs)

        with patch.object(runtime, "worker", spy):
            snapshot = await self.decide(action="retry", timeout=120)
        self.assertEqual(self.gate(snapshot), "techspec")
        self.assertTrue(seen)
        self.assertEqual(set(seen), {120})  # the retried job and every later job use the raised timeout

    async def test_gate_approval_can_raise_the_job_timeout_for_later_steps(self):
        snapshot = await self.start()
        self.assertEqual(self.gate(snapshot), "techspec")
        seen = []
        original = runtime.worker

        async def spy(*args, **kwargs):
            seen.append(kwargs["timeout"])
            return await original(*args, **kwargs)

        with patch.object(runtime, "worker", spy):
            snapshot = await self.decide(action="approve", timeout=77)
        self.assertEqual(self.gate(snapshot), "release")
        self.assertTrue(seen)
        self.assertEqual(set(seen), {77})
        self.assertEqual(snapshot.values["decisions"][-1]["timeout"], 77)

    async def test_failed_job_blocks_until_explicit_retry_bound_to_that_attempt(self):
        self.behaviors({"prd-draft-1": "nonzero"})
        snapshot = await self.start()
        self.assertEqual(self.gate(snapshot), "blocked")
        self.assertEqual(snapshot.values["blocked"]["node"], "prd_draft")
        count = len(self.calls())
        snapshot = await flow_task.advance(self.task, None)  # resume without a decision
        self.assertEqual(self.gate(snapshot), "blocked")
        self.assertEqual(len(self.calls()), count)
        snapshot = await self.decide(action="retry")  # still failing: one attempt, then blocked again
        self.assertEqual(self.gate(snapshot), "blocked")
        self.assertEqual(len(self.calls()), count + 1)
        self.behaviors({})
        snapshot = await flow_task.advance(self.task, None)  # the old grant is spent
        self.assertEqual(len(self.calls()), count + 1)
        snapshot = await self.decide(action="retry")
        self.assertEqual(self.gate(snapshot), "techspec")  # P2: no PRD gate
        self.assertEqual(self.task.state.get("prd-draft-1")["attempts"], 3)
        self.assertEqual(len(list((self.task.directory / "attempts").iterdir())), 2)

    async def test_call_limit_blocks_and_retry_can_raise_it(self):
        snapshot = await self.start(max_calls=2)
        self.assertEqual(self.gate(snapshot), "blocked")
        self.assertIn("call limit", snapshot.values["blocked"]["reasons"][0])
        self.assertEqual(len(self.calls()), 2)
        snapshot = await self.decide(action="retry", max_calls=40)
        self.assertEqual(self.gate(snapshot), "techspec")

    async def test_crash_after_paid_implement_reuses_job_and_commit(self):
        snapshot = await self.start()
        original = workspace.run_tests

        async def crash(*args, **kwargs):
            raise RuntimeError("supervisor crashed")

        with patch.object(workspace, "run_tests", side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, "supervisor crashed"):
                await self.decide(action="approve")
        calls = self.jobs()
        head = workspace.head(self.task.worktree)
        self.assertEqual(calls.count("implement-1"), 1)
        with patch.object(workspace, "run_tests", side_effect=original):
            snapshot = await flow_task.advance(self.task, None)
        self.assertEqual(self.gate(snapshot), "release")
        self.assertEqual(self.jobs().count("implement-1"), 1)
        self.assertEqual(workspace.head(self.task.worktree), head)

    async def test_triage_can_raise_but_not_lower_the_risk_floor(self):
        self.behaviors({"triage": "risk_P3"})
        snapshot = await self.start(risk="P1")
        self.assertEqual(snapshot.values["risk"], "P1")
        self.assertEqual(self.gate(snapshot), "prd")

    async def test_p0_uses_three_independent_reviewers_including_qa(self):
        self.behaviors({"triage": "risk_P0"})
        snapshot = await self.start(risk="P2")
        self.assertEqual(snapshot.values["risk"], "P0")
        for _ in range(2):
            snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "release")
        reviewers = {c["job"]: c["worker"] for c in self.calls() if c["job"].startswith("code-review-")}
        self.assertEqual(reviewers, {"code-review-code-reviewer-1": "claude",
                                     "code-review-critical-invariants-reviewer-1": "claude",
                                     "code-review-adversarial-qa-1": "antigravity"})
        # Only Antigravity, which aborts on a failed tool call, gets the absolute-path reminder.
        hinted = {c["job"]: c["path_hint"] for c in self.calls() if c["job"].startswith("code-review-")}
        self.assertEqual(hinted, {"code-review-code-reviewer-1": False,
                                  "code-review-critical-invariants-reviewer-1": False,
                                  "code-review-adversarial-qa-1": True})
        self.assertEqual(next(c for c in self.calls() if c["job"] == "implement-1")["worker"], "codex")
        # Stage bindings tune one persona per tier: P0 implements at high effort, reviews with Opus.
        manifest = lambda job, worker: runtime.read_json(self.task.directory / "jobs" / job / worker / "manifest.json")
        self.assertEqual(manifest("implement-1", "codex")["requested_effort"], "high")
        self.assertEqual(manifest("code-review-code-reviewer-1", "claude")["requested_model"], "claude-opus-5-5")
        self.assertEqual(manifest("code-review-critical-invariants-reviewer-1", "claude")["requested_effort"], "xhigh")

    async def test_p3_skips_documents_and_records_write_mode_permission_denials(self):
        # Claude write mode records denials instead of failing: give P3 a Claude implementer.
        roster, flow = (runtime.read_json(self.root / f"config/{n}.json") for n in ("personas", "flow"))
        personas = roster["personas"]
        personas["claude-engineer"] = {**personas["engineer"], "runtime": "claude", "model": None}
        personas["codex-reviewer"] = {**personas["code-reviewer"], "runtime": "codex", "model": None}
        flow["roles"]["implement"]["P3"], flow["roles"]["code_review"]["P3"] = "claude-engineer", ["codex-reviewer"]
        flow["kinds"] = {"code": {}}  # the design kind's Claude UI reviewer would review a Claude implementer
        runtime.write_json(self.root / "config/personas.json", roster)
        runtime.write_json(self.root / "config/flow.json", flow)
        self.behaviors({"triage": "risk_P3", "implement-1": "structured_denial"})
        snapshot = await self.start(risk="P3")
        self.assertEqual(self.gate(snapshot), "release")
        self.assertEqual(self.jobs(), ["triage", "implement-1", "code-review-codex-reviewer-1"])
        impl = snapshot.values["implementation"]
        self.assertTrue(impl["permission_denials"])
        self.assertEqual(next(c for c in self.calls() if c["job"] == "implement-1")["worker"], "claude")

    async def test_research_gate_runs_the_research_graph_before_the_prd(self):
        self.behaviors({"triage": "needs_research"})
        snapshot = await self.start(risk="P1")
        self.assertEqual(self.gate(snapshot), "research")
        brief = flow_task.copy_brief(self.task, self.root / "inputs/brief.md")
        snapshot = await self.decide(action="research", brief=brief)
        self.assertEqual(self.gate(snapshot), "prd")
        research = snapshot.values["research"]
        self.assertEqual(research["status"], "complete")
        self.assertEqual(sum(c["job"].startswith(("research-", "audit-", "review-", "adjudication-", "synthesis-"))
                             for c in self.calls()), 13)
        self.assertTrue((self.task.directory / "research/final-report.md").is_file())
        self.assertEqual(self.packet_context("prd-draft-1", "codex")["research"]["status"], "complete")

    def test_roster_rejects_self_review_and_unverified_write_runtime(self):
        flow = runtime.read_json(runtime.ROOT / "config/flow.json")
        personas = runtime.read_json(runtime.ROOT / "config/personas.json")["personas"]
        agents = flow_task.demo_agents(self.root)
        check_roster(flow, personas, agents)
        same = copy.deepcopy(flow)
        same["roles"]["code_review"]["P2"] = ["triage-lead"]  # codex reviewing codex
        with self.assertRaisesRegex(ValueError, "different runtime"):
            check_roster(same, personas, agents)
        own = copy.deepcopy(flow)
        own["kinds"]["docs"]["roles"]["code_review"] = ["product-manager"]  # codex reviewing the codex writer
        with self.assertRaisesRegex(ValueError, "different runtime"):
            check_roster(own, personas, agents)
        for bad, error in (({"persona": "engineer", "runtime": "claude"}, "must be a persona id"),  # no runtime swap
                           ({"persona": "engineer", "effort": "extreme"}, "Invalid effort")):
            tuned = copy.deepcopy(flow)
            tuned["roles"]["implement"]["P2"] = bad
            with self.assertRaisesRegex(ValueError, error):
                check_roster(tuned, personas, agents)
        writer = copy.deepcopy(flow)
        writer["roles"]["implement"]["P3"] = "adversarial-qa"
        with self.assertRaisesRegex(ValueError, "Antigravity"):
            check_roster(writer, personas, agents)
        no_release = copy.deepcopy(flow)
        no_release["gates"]["P3"] = []
        with self.assertRaisesRegex(ValueError, "release"):
            check_roster(no_release, personas, agents)
        with self.assertRaisesRegex(ValueError, "not supported"):
            runtime.cli_args("antigravity", agents["antigravity"], self.root, self.root, {}, 10, "write")

    def test_prd_schema_separates_when_from_then_and_names_an_empty_field(self):
        from lab.flow import contracts as flow_contracts
        fields = flow_contracts.PRD["properties"]["acceptance_criteria"]["items"]["properties"]
        for key in ("given", "when", "then"):
            self.assertEqual(fields[key]["type"], "string")
            self.assertTrue(fields[key]["description"].strip())
        self.assertIn("then", fields["when"]["description"])
        prd = {"title": "t", "summary": "s", "problem": "p", "goals": [], "non_goals": [], "users": [],
               "requirements": [{"id": "R1", "text": "r", "priority": "must"}],
               "acceptance_criteria": [{"id": "AC1", "requirement_ids": ["R1"], "given": "g",
                                        "when": "When x; Then y", "then": " "}],
               "risks": [], "open_questions": [], "resolutions": []}
        with self.assertRaisesRegex(ValueError, r"^Acceptance criterion AC1: field 'then' is empty$"):
            flow_contracts.validate_prd(prd, [])
        prd["acceptance_criteria"][0].update(when="x", then="y")
        flow_contracts.validate_prd(prd, [])

    def test_workers_never_load_agents_md_or_claude_md_from_disk(self):
        # Rules reach workers only through the sealed packet.
        cfg = {"prefix": ["codex"], "model": "m", "effort": None}
        for access in ("packet", "read", "write"):
            self.assertIn("project_doc_max_bytes=0", runtime.cli_args("codex", cfg, self.root, self.root, {}, 10, access))
            claude = runtime.cli_args("claude", cfg, self.root, self.root, {}, 10, access)
            self.assertEqual(claude[claude.index("--setting-sources") + 1], "")

    async def test_lab_and_project_rules_are_sealed_into_every_packet(self):
        (self.root / "rules").mkdir()
        (self.root / "rules/money.md").write_text("Never use float for money.\n")
        (self.root / "rules/README.md").write_text("How to write rules, not a rule.\n")
        files = {"AGENTS.md": "# Project rules\n", "docs/style.md": "Name tests after behaviour.\n"}
        with patch.dict(flow_task.DEMO_FILES, files):
            await self.start(rule_paths=["docs/style.md", "AGENTS.md"])
            self.assertEqual([r["source"] for r in self.task.rules],
                             ["lab:rules/money.md", "repo:AGENTS.md", "repo:docs/style.md"])
            for paths, error in ((["docs/missing.md"], "docs/missing.md is not a file"),
                                 (["docs"], "docs is not a file")):  # a directory is not a rule
                with self.assertRaisesRegex(ValueError, error):
                    await flow_task.create(self.root, demo=True, rule_paths=paths)
        self.assertEqual(sorted(p.name for p in (self.root / "tasks").iterdir()), [self.task.id])  # no leftovers
        snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "release")
        for job, worker in (("techspec-draft-1", "codex"), ("implement-1", "codex"),
                            ("code-review-code-reviewer-1", "claude")):
            packet = (self.task.directory / "jobs" / job / worker / "INPUT.md").read_text()
            self.assertIn("<<<RULE lab:rules/money.md\nNever use float for money.\nRULE>>>", packet)
            self.assertIn("<<<RULE repo:AGENTS.md\n# Project rules\nRULE>>>", packet)
            self.assertNotIn("not a rule", packet)

    async def test_task_skills_guide_code_stages_and_only_implement_runs_their_scripts(self):
        folder = ".claude/skills/fee-rounding"
        files = {f"{folder}/SKILL.md": "Round fees up with integer division.\n",
                 f"{folder}/scripts/check.py": "print('ok')\n",
                 f"{folder}/scripts/data.json": "{}\n", f"{folder}/scripts/lib/util.py": "\n"}
        with patch.dict(flow_task.DEMO_FILES, files):
            await self.start(skill_names=["fee-rounding", "code-review-excellence"])
            with self.assertRaisesRegex(ValueError, "Unknown skill nope"):
                await flow_task.create(self.root, demo=True, skill_names=["nope"])
        self.assertEqual(self.task.settings["skills"], [{"name": "fee-rounding", "source": f"repo:{folder}"},
                                                        {"name": "code-review-excellence", "source": "lab"}])
        command = f"python3 {folder}/scripts/check.py"  # not data files or helper modules
        self.assertEqual(self.task.settings["skill_scripts"], [command])
        allowed = runtime.cli_args("claude", {"model": "m"}, self.root, self.root, {}, 10, "write",
                                   self.task.settings["allow_bash"])
        self.assertIn(f"Bash({command} *)", allowed)
        self.assertNotIn("Bash(python3 *)", allowed)
        await self.decide(action="approve")
        jobs = self.task.directory / "jobs"
        for job, worker in (("techspec-draft-1", "codex"), ("implement-1", "codex"),
                            ("code-review-code-reviewer-1", "claude")):
            packet = (jobs / job / worker / "INPUT.md").read_text()
            self.assertEqual(packet.count("## Project skill fee-rounding/SKILL.md"), 1, job)
            # Already configured for code-review in flow.json: never inlined twice.
            self.assertEqual(packet.count("## Imported skill code-review-excellence/SKILL.md"), 1, job)
            self.assertEqual(f"- `{command}`" in packet, job == "implement-1", job)
        self.assertNotIn("Project skill", (jobs / "prd-draft-1/codex/INPUT.md").read_text())

    async def test_docs_and_content_kinds_go_from_writer_to_editor_without_prd(self):
        for kind, writer, reviewer, written in (("docs", "technical-writer", "docs-verifier", "docs/fees.md"),
                                                ("content", "copywriter", "content-editor", "content/home.md")):
            (self.root / "tests/calls.jsonl").unlink(missing_ok=True)
            # The demo repo's fee tests fail until someone writes the code; a docs task gets its own check.
            snapshot = await self.start(kind=kind, test_command=f"{sys.executable} -c pass")
            self.assertEqual(self.gate(snapshot), "release", kind)
            self.assertEqual(self.jobs(), ["triage", "implement-1", f"code-review-{reviewer}-1"])
            self.assertEqual([(c["worker"], c["stage"]) for c in self.calls()[1:]],
                             [("codex", f"write-{kind}"), ("claude", f"{kind}-review")])
            packet = (self.task.directory / "jobs/implement-1/codex/INPUT.md").read_text()
            self.assertIn(f"# Persona: {writer}", packet)
            if kind == "content":  # both the writer and the editor carry the anti-AI-writing skill
                editor = (self.task.directory / f"jobs/code-review-{reviewer}-1/claude/INPUT.md").read_text()
                for text in (packet, editor):
                    self.assertIn("## Imported skill avoid-ai-writing/SKILL.md", text)
            self.assertIn(written, snapshot.values["implementation"]["changed_files"])
            self.assertNotIn("prd", snapshot.values)

    async def test_design_kind_adds_a_ux_spec_gate_and_a_ui_reviewer(self):
        snapshot = await self.start(kind="design")  # P2: no PRD gate, but design always gates the UX spec
        self.assertEqual(self.gate(snapshot), "uxspec")
        self.assertEqual(self.jobs(), ["triage", "prd-draft-1", "prd-review-requirements-reviewer-1",
                                       "uxspec-draft-1", "uxspec-review-ui-reviewer-1"])
        self.assertTrue((self.task.directory / "docs/uxspec.md").is_file())
        snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "techspec")
        self.assertIn("uxspec", self.packet_context("techspec-draft-1", "codex"))  # techspec builds on the UX spec
        snapshot = await self.decide(action="approve")
        self.assertEqual(self.gate(snapshot), "release")
        reviews = {(c["job"], c["stage"]) for c in self.calls() if c["job"].startswith("code-review-")}
        self.assertEqual(reviews, {("code-review-code-reviewer-1", "code-review"),
                                   ("code-review-ui-reviewer-1", "ui-review")})
        with self.assertRaisesRegex(ValueError, "Unknown kind"):
            await flow_task.create(self.root, demo=True, kind="video")

    async def test_list_shows_each_task_and_what_it_waits_for(self):
        await self.start()
        (self.root / "tasks/broken").mkdir()
        (self.root / "tasks/broken/task.json").write_text("{}")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(await run_flow.list_tasks(self.root), 0)
        rows = out.getvalue().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(row.startswith(self.task.id) and "awaiting techspec" in row
                            and "Phí chuyển khoản" in row for row in rows), rows)
        self.assertTrue(any(row.startswith("broken  error:") for row in rows), rows)

    async def test_sealed_task_inputs_cannot_change(self):
        await self.start()
        (self.task.directory / "snapshots/request.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "Sealed task input changed"):
            flow_task.load(self.root, self.task.directory)

    async def test_release_revise_grants_more_automatic_fix_rounds(self):
        self.behaviors({f"code-review-code-reviewer-{n}": "blocking" for n in range(1, 6)})
        snapshot = await self.start()
        snapshot = await self.decide(action="approve")
        self.assertEqual(snapshot.values["impl_round"], 3)
        snapshot = await self.decide(action="revise", note="Sửa hết finding của reviewer")
        self.assertEqual(self.gate(snapshot), "release")
        self.assertEqual(snapshot.values["impl_round"], 5)  # 3 + max_fix_rounds, not a single round
        human = [f for f in self.packet_context("implement-4", "codex")["findings_to_resolve"]
                 if f["source"] == "human"]
        self.assertEqual(len(human), 1)

    async def test_unresolved_doc_blockers_escalate_even_without_a_gate_for_the_tier(self):
        self.behaviors({"prd-review-requirements-reviewer-1": "blocking", "prd-review-requirements-reviewer-2": "blocking"})
        snapshot = await self.start()  # P2: normally no PRD gate
        self.assertEqual(self.gate(snapshot), "prd")
        summary = (self.task.directory / snapshot.interrupts[0].value["summary"]).read_text()
        self.assertIn("requirements-reviewer/F1", summary)

    async def test_interrupted_research_retry_is_not_repeated_without_a_new_decision(self):
        self.behaviors({"triage": "needs_research", "audit-A": "nonzero"})
        await self.start(risk="P1")
        snapshot = await self.decide(action="research", brief=flow_task.copy_brief(self.task, self.root / "inputs/brief.md"))
        self.assertEqual(self.gate(snapshot), "blocked")
        count = self.jobs().count("audit-A")
        with patch.object(pipeline.Pipeline, "export", side_effect=RuntimeError("crash before export")):
            with self.assertRaisesRegex(RuntimeError, "crash before export"):
                await self.decide(action="retry")
        self.assertEqual(self.jobs().count("audit-A"), count + 1)
        snapshot = await flow_task.advance(self.task, None)  # resume after the crash
        self.assertEqual(self.gate(snapshot), "blocked")
        self.assertEqual(self.jobs().count("audit-A"), count + 1)

    async def test_unknown_research_skill_is_rejected_when_the_task_is_created(self):
        with self.assertRaisesRegex(ValueError, "Unknown installed skill"):
            await flow_task.create(self.root, demo=True, research_skills=["typo"])
        self.assertFalse((self.root / "tasks").exists())

    def test_workspace_handles_renames_non_ascii_paths_and_non_utf8_content(self):
        repo = self.root / "repo"
        repo.mkdir()
        workspace.git(repo, "init", "-q")
        (repo / "a.py").write_text("x = 1\n")
        (repo / "latin.txt").write_bytes("caf\xe9\n".encode("latin-1"))
        workspace.git(repo, "add", "-A")
        workspace.git(repo, *workspace.COMMITTER, "commit", "-q", "-m", "base")
        base = workspace.head(repo)
        workspace.git(repo, "mv", "a.py", "b.py")
        (repo / "phí.py").write_text("fee = 1\n")
        (repo / "latin.txt").write_bytes("na\xefve\n".encode("latin-1"))
        tip = workspace.commit_all(repo, "change")
        self.assertEqual(set(workspace.changed_files(repo, base, tip)), {"a.py", "b.py", "phí.py", "latin.txt"})
        self.assertIn("phí.py", workspace.known_files(repo, base, tip))
        text, truncated = workspace.diff_text(repo, base, tip, 100_000)
        self.assertFalse(truncated)
        self.assertIn("latin.txt", text)
        (repo / "latin.txt").write_bytes("\xff\xfe\n".encode("latin-1"))
        workspace.archive_and_reset(repo, self.root / "partial.patch")
        self.assertIn(b"\xff\xfe", (self.root / "partial.patch").read_bytes())
        self.assertFalse(workspace.dirty(repo))

    def test_run_tests_kills_the_process_group_on_timeout(self):
        import asyncio
        log = self.root / "t.log"
        result = asyncio.run(workspace.run_tests(self.root, ["sh", "-c", "sleep 30 & sleep 30"], 0.5, log))
        self.assertEqual(result["status"], "timeout")
        alive = subprocess.run(["pgrep", "-f", "sleep 30"], capture_output=True, text=True).stdout.split()
        self.assertFalse([pid for pid in alive if Path(f"/proc/{pid}/cwd").exists()
                          and Path(f"/proc/{pid}/cwd").resolve() == self.root.resolve()])


if __name__ == "__main__":
    unittest.main()
