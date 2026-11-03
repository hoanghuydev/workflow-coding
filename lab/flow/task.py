"""Task creation, sealing and graph execution with a durable LangGraph checkpoint.

tasks/<task-id>/
  task.json, seal.json, snapshots/   sealed request, roster, policy, protocols, skills, rules
  checkpoints.db                     LangGraph state (thread_id = task id)
  state.db, jobs/, attempts/         model-call ledger and raw CLI artifacts
  worktree/                          git worktree on branch flow/<task-id>
  docs/, gates/, tests/, research/   rendered documents, gate summaries, test logs
  report.md
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .. import contracts as research_contracts, pipeline, runtime
from ..jobs import JobRunner
from ..state import State, now
from . import workspace
from .config import check_roster
from .contracts import RISKS
from .graph import FlowContext, build_graph

INLINE_LIMIT = 200_000  # bytes per rule file or skill inlined into every packet
PROJECT_RULE_FILES = ("AGENTS.md", "CLAUDE.md")
PROJECT_SKILL_DIRS = (".agents/skills", ".claude/skills")
# Skills chosen with --skill guide the stages that read or write code; their scripts run only in implement.
TASK_SKILL_STAGES = ("techspec", "techspec-review", "implement", "code-review", "qa")
SCRIPT_RUNNERS = {".py": "python3", ".sh": "bash", ".js": "node"}
PROTOCOLS = ("triage", "prd", "prd-review", "techspec", "techspec-review", "implement", "code-review", "qa")
DEMO_REQUEST = """# Phí chuyển khoản

Viết hàm `transfer_fee(amount)` trong `fees.py` tính phí chuyển khoản 1,1% theo đồng,
làm tròn lên. Số tiền âm phải bị từ chối bằng `ValueError`. Repo đã có test mô tả hành vi.
"""
DEMO_FILES = {
    ".gitignore": "__pycache__/\n",
    "fees.py": "def transfer_fee(amount: int) -> int:\n    raise NotImplementedError\n",
    "test_fees.py": ("import unittest\n\nfrom fees import transfer_fee\n\n\n"
                     "class FeeTests(unittest.TestCase):\n"
                     "    def test_rounds_up_to_whole_dong(self):\n"
                     "        self.assertEqual(transfer_fee(100_000), 1_100)\n"
                     "        self.assertEqual(transfer_fee(1), 1)\n\n"
                     "    def test_rejects_negative_amount(self):\n"
                     "        with self.assertRaises(ValueError):\n"
                     "            transfer_fee(-1)\n"),
}


@dataclass
class Task:
    root: Path
    directory: Path
    settings: dict
    flow: dict
    personas: dict
    agents: dict
    policy: dict
    protocols: dict
    bundles: dict
    rules: list
    request: str
    state: State
    runner: JobRunner

    @property
    def id(self):
        return self.settings["task_id"]

    @property
    def worktree(self):
        return self.directory / "worktree"

    def close(self):
        self.state.close()


def checked(source, text):
    if len(text.encode("utf-8")) > INLINE_LIMIT:
        raise ValueError(f"{source} is over {INLINE_LIMIT} bytes")
    return text


def is_file(repo, base_sha, path):
    try:
        return workspace.git(repo, "cat-file", "-t", f"{base_sha}:{path}").strip() == "blob"
    except ValueError:
        return False


def repo_file(repo, base_sha, path):
    if not is_file(repo, base_sha, path):
        raise ValueError(f"{path} is not a file in {repo} at {base_sha[:12]}")
    return workspace.git(repo, "show", f"{base_sha}:{path}")


def load_rules(root, repo, base_sha, rule_paths=()):
    """General rules from this lab's rules/, project rules from the target repo at the base commit."""
    rules = [{"source": f"lab:rules/{path.name}", "text": path.read_text(encoding="utf-8-sig")}
             for path in sorted((root / "rules").glob("*.md")) if path.name != "README.md"]
    defaults = [name for name in PROJECT_RULE_FILES if is_file(repo, base_sha, name)]
    rules += [{"source": f"repo:{path}", "text": repo_file(repo, base_sha, path)}
              for path in dict.fromkeys([*defaults, *rule_paths])]
    return [rule for rule in rules if checked(rule["source"], rule["text"]).strip()]


def task_skills(root, repo, base_sha, names, lock):
    """--skill names: a skill committed in the target repo, else one installed in this lab.
    Lab skills are third-party Markdown only; a project skill's top-level scripts/ are repo code."""
    installed = {entry["name"] for entry in lock["skills"]}
    skills = []
    for name in dict.fromkeys(names):
        folder = next((f"{d}/{name}" for d in PROJECT_SKILL_DIRS if is_file(repo, base_sha, f"{d}/{name}/SKILL.md")),
                      None)
        if folder:
            files = [path[len(folder) + 1:] for path in workspace.paths(
                workspace.git(repo, "ls-tree", "-r", "-z", "--name-only", base_sha, "--", folder + "/"))]
            docs = ["SKILL.md", *sorted(f for f in files if f.endswith(".md") and f != "SKILL.md")]
            skills.append({"name": name, "source": f"repo:{folder}", "text": "\n\n".join(
                f"## Project skill {name}/{f}\n" + repo_file(repo, base_sha, f"{folder}/{f}") for f in docs),
                "scripts": [f"{folder}/{f}" for f in sorted(files) if f.count("/") == 1
                            and f.startswith("scripts/") and Path(f).suffix in SCRIPT_RUNNERS]})
        elif name in installed:
            skills.append({"name": name, "source": "lab", "text": pipeline.skill_bundle(root, [name], lock),
                           "scripts": []})
        else:
            raise ValueError(f"Unknown skill {name}: not in {', '.join(PROJECT_SKILL_DIRS)} of {repo} at "
                             f"{base_sha[:12]}, nor installed in this lab")
        checked(f"Skill {name}", skills[-1]["text"])
    return skills


def scripts_section(commands):
    return ("## Skill scripts (implement stage only)\n"
            "You may run these skill scripts from the worktree root, only in these forms followed by arguments "
            "(no other interpreter, cd, pipes or chained commands):\n"
            + "".join(f"- `{command}`\n" for command in commands)
            + "Report each run in commands_run; the supervisor still runs the test command itself.")


def demo_agents(root):
    return {name: {"prefix": [sys.executable, str(root / "tests/fake_cli.py")], "model": "synthetic-model",
                   "effort": None} for name in pipeline.WORKERS}


def demo_repo(path):
    path.mkdir(parents=True)
    for name, text in DEMO_FILES.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", *workspace.COMMITTER, "commit", "-q", "-m", "demo: failing fee tests"], cwd=path, check=True)
    return path


async def create(root, *, request_path=None, repo=None, base="HEAD", test_command=None, risk=None, brief=None,
                 max_calls=None, timeout=900, demo=False, research_skills=(), rule_paths=(), skill_names=()):
    root = Path(root).resolve()
    flow = runtime.read_json(root / "config/flow.json")
    personas = runtime.read_json(root / "config/personas.json")["personas"]
    agents = runtime.check_agents(demo_agents(root) if demo else runtime.read_json(root / "config/agents.local.json"))
    check_roster(flow, personas, agents)
    policy = runtime.check_policy(runtime.read_json(root / "config/agy-research.json"))
    if risk is not None and risk not in RISKS:
        raise ValueError("--risk must be one of P0..P3")
    if timeout <= 0 or (max_calls is not None and max_calls <= 0):
        raise ValueError("Timeout and max-calls must be positive")
    if demo:
        request = DEMO_REQUEST
        risk = risk or "P2"
    else:
        if not request_path or not repo:
            raise ValueError("start needs --request and --repo (or --demo)")
        request = Path(request_path).read_text(encoding="utf-8-sig")
    if not request.strip():
        raise ValueError("Request is empty")
    brief_text = None
    if brief:
        brief_text = Path(brief).read_text(encoding="utf-8-sig")
        research_contracts.extract_sources(brief_text)
    unknown = set(flow.get("skills", {})) - set(PROTOCOLS)
    if unknown:
        raise ValueError(f"config/flow.json skills names unknown stages: {', '.join(sorted(unknown))}")
    lock = runtime.read_json(root / "config/skills.lock.json")
    bundles = {name: pipeline.skill_bundle(root, flow.get("skills", {}).get(name, []), lock) for name in PROTOCOLS}
    pipeline.skill_bundle(root, research_skills, lock)  # fail now, not days later at the research node
    protocols = {name: (root / "protocols/flow" / f"{name}.md").read_text(encoding="utf-8") for name in PROTOCOLS}
    versions = await pipeline.versions(agents)

    task_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    directory = root / "tasks" / task_id
    directory.mkdir(parents=True)
    try:
        if demo:
            repo = demo_repo(directory / "demo-repo")
            test_command = test_command or shlex.join([sys.executable, "-m", "unittest", "-q"])
        repo = Path(repo).resolve()
        base_sha = workspace.resolve(repo, base)
        rules = load_rules(root, repo, base_sha, rule_paths)
        skills = task_skills(root, repo, base_sha, skill_names, lock)
        for stage in TASK_SKILL_STAGES:
            configured = flow.get("skills", {}).get(stage, [])
            bundles[stage] = "\n\n".join(filter(None, [bundles[stage], *(
                s["text"] for s in skills if not (s["source"] == "lab" and s["name"] in configured))]))
        scripts = [shlex.join([SCRIPT_RUNNERS[Path(path).suffix], path]) for s in skills for path in s["scripts"]]
        if scripts:
            bundles["implement"] += "\n\n" + scripts_section(scripts)
        argv = shlex.split(test_command) if test_command else []
        snapshots = directory / "snapshots"
        snapshots.mkdir()
        (snapshots / "request.md").write_text(request, encoding="utf-8")
        if brief_text is not None:
            (snapshots / "research-brief.md").write_text(brief_text, encoding="utf-8")
        for name, value in (("flow", flow), ("personas", personas), ("agents", agents), ("policy", policy),
                            ("protocols", protocols), ("bundles", bundles), ("rules", rules), ("versions", versions)):
            runtime.write_json(snapshots / f"{name}.json", value)
        settings = {"task_id": task_id, "created_at_utc": now(), "repo": str(repo), "base_ref": base,
                    "base_sha": base_sha, "branch": f"flow/{task_id}", "test_command": argv,
                    "allow_bash": [*flow.get("allow_bash", []), *([shlex.join(argv)] if argv else []), *scripts],
                    "risk": risk, "demo": demo, "timeout": timeout, "max_calls": max_calls or flow["max_calls"],
                    "research_skills": list(research_skills),
                    "skills": [{"name": s["name"], "source": s["source"]} for s in skills], "skill_scripts": scripts}
        runtime.write_json(directory / "task.json", settings)
        files = {str(p.relative_to(directory)): runtime.digest(p)
                 for p in sorted([directory / "task.json", *snapshots.rglob("*")]) if p.is_file()}
        runtime.write_json(directory / "seal.json", {"created_at_utc": now(), "files": files})
        workspace.create_worktree(repo, base_sha, directory / "worktree", settings["branch"])
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)  # a failed start leaves no half-made task
        raise
    return directory


def load(root, directory):
    directory = Path(directory).resolve()
    if not (directory / "seal.json").is_file():
        raise ValueError(f"Not a task directory: {directory}")
    for relative, expected in runtime.read_json(directory / "seal.json")["files"].items():
        path = directory / relative
        if not path.is_file() or runtime.digest(path) != expected:
            raise ValueError(f"Sealed task input changed: {relative}")
    snap = directory / "snapshots"
    settings = runtime.read_json(directory / "task.json")
    agents = runtime.check_agents(runtime.read_json(snap / "agents.json"))
    policy = runtime.read_json(snap / "policy.json")
    state = State(directory)
    runner = JobRunner(directory, agents, policy, state, timeout=settings["timeout"], max_calls=settings["max_calls"])
    return Task(root=Path(root).resolve(), directory=directory, settings=settings,
                flow=runtime.read_json(snap / "flow.json"), personas=runtime.read_json(snap / "personas.json"),
                agents=agents, policy=policy, protocols=runtime.read_json(snap / "protocols.json"),
                bundles=runtime.read_json(snap / "bundles.json"),
                rules=runtime.read_json(snap / "rules.json"),
                request=(snap / "request.md").read_text(encoding="utf-8"), state=state, runner=runner)


async def check_versions(task):
    """Tasks can wait days at a gate, so a CLI update is recorded, not fatal."""
    current = await pipeline.versions(task.agents)
    sealed = runtime.read_json(task.directory / "snapshots/versions.json")
    if current != sealed:
        history = task.directory / "versions-history.json"
        entries = runtime.read_json(history) if history.is_file() else []
        if not entries or entries[-1]["versions"] != current:
            runtime.write_json(history, [*entries, {"at_utc": now(), "versions": current}])
        print(f"warning: CLI versions differ from the sealed task: {current}", flush=True)


async def advance(task, payload=None, *, invoke=True):
    """Run the graph until it finishes or pauses at a gate and return the state snapshot.
    payload None continues from the last checkpoint; invoke=False only reads state."""
    async with AsyncSqliteSaver.from_conn_string(str(task.directory / "checkpoints.db")) as saver:
        app = build_graph().compile(checkpointer=saver, name="work-flow")
        config = {"configurable": {"thread_id": task.id}}
        if invoke:
            # durability="sync": every step is on disk before the next one starts.
            await app.ainvoke(payload, config, context=FlowContext(task), durability="sync")
        return await app.aget_state(config)


def copy_brief(task, brief):
    text = Path(brief).read_text(encoding="utf-8-sig")
    research_contracts.extract_sources(text)
    relative = f"snapshots/research-brief-{uuid4().hex[:8]}.md"
    (task.directory / relative).write_text(text, encoding="utf-8")
    return relative


def initial_input(task):
    brief = task.directory / "snapshots/research-brief.md"
    return {"decisions": [], **({"research_brief": "snapshots/research-brief.md"} if brief.is_file() else {})}

