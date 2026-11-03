"""Work flow CLI: triage, research, PRD, techspec, implement, test and review with human gates.

Default execution calls the configured CLIs and uses account quota; --demo is offline.
"""
import argparse
import asyncio
from pathlib import Path
import signal
import sys

from langgraph.types import Command

from lab import runtime
from lab.flow import task as flow_task
from lab.flow.contracts import RISKS
from lab.flow.graph import build_graph
from lab.state import run_lock


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="SePay work flow with human gates (LangGraph)")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Create a task and run until the first human gate")
    start.add_argument("--request", help="Markdown file describing the work")
    start.add_argument("--repo", help="Target git repository; agents work in a new worktree")
    start.add_argument("--base", default="HEAD", help="Base ref for branch flow/<task-id> (default: HEAD)")
    start.add_argument("--test", help="Test command the supervisor runs in the worktree, e.g. 'go test ./...'")
    start.add_argument("--risk", choices=RISKS, help="Risk floor; triage may raise it, never lower it")
    start.add_argument("--brief", help="Research brief with Source <ID> sections; research runs before the PRD")
    start.add_argument("--research-skill", action="append", default=[], help="Installed skill for researchers")
    start.add_argument("--rules", action="append", default=[],
                       help="Extra project rule file, as a path in the target repo (AGENTS.md and CLAUDE.md "
                            "are read automatically; lab rules/*.md always apply)")
    start.add_argument("--skill", action="append", default=[],
                       help="Skill for the code stages: one in the target repo (.agents/skills, .claude/skills) "
                            "or installed in this lab")
    start.add_argument("--max-calls", type=int, help="Model call limit for the task (default: config/flow.json)")
    start.add_argument("--timeout", type=int, default=900, help="Seconds per CLI job, not a money cap")
    start.add_argument("--demo", action="store_true", help="Synthetic CLIs and a throwaway demo repository")
    start.add_argument("--auto-approve", action="store_true", help="With --demo only: approve every gate")
    for name, text in (("status", "Show state and the pending gate"),
                       ("resume", "Continue after a crash or Ctrl-C; makes no gate decision")):
        sub.add_parser(name, help=text).add_argument("task", help="Task id or directory")
    for name, text in (("approve", "Approve the pending gate"), ("revise", "Send the stage back with a note"),
                       ("reject", "Stop the task")):
        parser_ = sub.add_parser(name, help=text)
        parser_.add_argument("task")
        parser_.add_argument("--note", default="", required=name == "revise")
        if name != "reject":
            parser_.add_argument("--risk", choices=RISKS, help="Change the risk tier from here on")
    research = sub.add_parser("research", help="Answer the research gate with a brief")
    research.add_argument("task")
    research.add_argument("--brief", required=True)
    retry = sub.add_parser("retry", help="Retry the blocked job after inspecting its logs")
    retry.add_argument("task")
    retry.add_argument("--max-calls", type=int, help="Raise the task's model call limit")
    sub.add_parser("list", help="List tasks and what each is waiting for")
    sub.add_parser("graph", help="Print the flow graph as Mermaid")
    args = parser.parse_args(argv)
    if args.command == "start":
        if args.auto_approve and not args.demo:
            parser.error("--auto-approve is only allowed with --demo")
        if not args.demo and not (args.request and args.repo):
            parser.error("start needs --request and --repo, or --demo")
    if getattr(args, "max_calls", None) is not None and args.max_calls <= 0:
        parser.error("--max-calls must be positive")
    return args


def task_dir(root, value):
    path = Path(value)
    return path if path.is_dir() else root / "tasks" / value


def show(task, snapshot):
    values = snapshot.values
    print(f"task {task.id}: risk {values.get('risk', '?')}, model calls "
          f"{task.state.calls()}/{values.get('max_calls') or task.settings['max_calls']}", flush=True)
    if snapshot.interrupts:
        gate = snapshot.interrupts[0].value
        print(f"awaiting human ({gate['kind']}): {task.directory / gate['summary']}")
        print(f"actions: {', '.join(gate['actions'])}")
        return 2
    if snapshot.next:
        print(f"stopped before {', '.join(snapshot.next)}; continue with: run_flow.py resume {task.id}")
        return 1
    print(f"finished: {values.get('status')}; report: {task.directory / 'report.md'}")
    return 0 if values.get("status") == "approved" else 1


def state_text(snapshot):
    if snapshot.interrupts:
        return f"awaiting {snapshot.interrupts[0].value['kind']}"
    if snapshot.next:
        return f"stopped before {', '.join(snapshot.next)}"
    return snapshot.values.get("status") or "not started"


async def list_tasks(root):
    rows = []
    for path in sorted((root / "tasks").glob("*/task.json")):
        try:
            task = flow_task.load(root, path.parent)
        except (ValueError, OSError) as exc:
            rows.append(f"{path.parent.name}  error: {exc}")
            continue
        try:
            snapshot = await flow_task.advance(task, invoke=False)
        finally:
            task.close()
        title = next((line.strip().lstrip("#").strip() for line in task.request.splitlines() if line.strip()), "")
        rows.append(f"{task.id}  {snapshot.values.get('risk') or task.settings['risk'] or '?':<2}  "
                    f"{state_text(snapshot):<26}  {title[:70]}")
    print("\n".join(rows) or "no tasks")
    return 0


async def run(args):
    root = runtime.ROOT
    if args.command == "graph":
        print(build_graph().compile().get_graph().draw_mermaid())
        return 0
    if args.command == "list":
        return await list_tasks(root)
    if args.command == "start":
        directory = await flow_task.create(
            root, request_path=args.request, repo=args.repo, base=args.base, test_command=args.test,
            risk=args.risk, brief=args.brief, max_calls=args.max_calls, timeout=args.timeout, demo=args.demo,
            research_skills=args.research_skill, rule_paths=args.rules, skill_names=args.skill)
        print(directory, flush=True)
    else:
        directory = task_dir(root, args.task)
    task = flow_task.load(root, directory)
    if args.command == "start":
        print("rules: " + (", ".join(rule["source"] for rule in task.rules) or "none"))
        print("task skills: " + (", ".join(f"{s['name']} ({s['source']})" for s in task.settings["skills"]) or "none"))
        if task.settings["skill_scripts"]:
            print("skill scripts (implement only): " + ", ".join(task.settings["skill_scripts"]))
        sys.stdout.flush()
    try:
        if args.command == "status":
            return show(task, await flow_task.advance(task, invoke=False))
        if args.command != "start":
            await flow_task.check_versions(task)
        with run_lock(task.directory):
            if args.command == "start":
                snapshot = await flow_task.advance(task, flow_task.initial_input(task))
                while args.auto_approve and snapshot.interrupts and snapshot.interrupts[0].value["kind"] != "blocked":
                    print(f"auto-approve {snapshot.interrupts[0].value['kind']} (demo)", flush=True)
                    snapshot = await flow_task.advance(task, Command(resume={"action": "approve",
                                                                             "note": "auto-approved (demo)"}))
                return show(task, snapshot)
            snapshot = await flow_task.advance(task, invoke=False)
            if args.command == "resume":
                if snapshot.interrupts or not snapshot.next:
                    return show(task, snapshot)
                return show(task, await flow_task.advance(task, None))
            if not snapshot.interrupts:
                raise ValueError("No gate is waiting for a decision; see run_flow.py status")
            gate = snapshot.interrupts[0].value
            if args.command not in gate["actions"]:
                raise ValueError(f"Gate {gate['kind']} accepts: {', '.join(gate['actions'])}")
            decision = {"action": args.command, "note": getattr(args, "note", "")}
            if getattr(args, "risk", None):
                decision["risk"] = args.risk
            if args.command == "research":
                decision["brief"] = flow_task.copy_brief(task, args.brief)
            if args.command == "retry" and args.max_calls:
                decision["max_calls"] = args.max_calls
            return show(task, await flow_task.advance(task, Command(resume=decision)))
    finally:
        task.close()


async def main(args):
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    return await run(args)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main(arguments())))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted; inspect job manifests, then: run_flow.py resume <task>", file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Flow error: {exc}", file=sys.stderr)
        sys.exit(1)
