"""Work flow CLI: triage, research, PRD, techspec, implement, test and review with human gates.

Default execution calls the configured CLIs and uses account quota; --demo is offline.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from langgraph.types import Command

from lab import runtime
from lab.flow import progress, task as flow_task
from lab.flow.contracts import RISKS
from lab.flow.graph import build_graph
from lab.state import run_lock

# Commands that call models. With --detach the supervisor runs in its own session, so closing the
# terminal or ending the assistant's session no longer kills the jobs it is running.
DETACHABLE = ("start", "approve", "revise", "retry", "research", "resume")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="workflow-coding: AI work flow with human gates (LangGraph)")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Create a task and run until the first human gate")
    start.add_argument("--request", help="Markdown file describing the work")
    start.add_argument("--repo", help="Target git repository; agents work in a new worktree")
    start.add_argument("--base", default="HEAD", help="Base ref for branch flow/<task-id> (default: HEAD)")
    start.add_argument("--test", help="Test command the supervisor runs in the worktree, e.g. 'go test ./...'")
    start.add_argument("--kind", default="code",
                       help="Kind of work from config/flow.json kinds: code (features, bugs), design (UI/UX), "
                            "docs, content (default: code)")
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
    for name, text in (("status", "Show state, progress and the pending gate"),
                       ("resume", "Continue after a crash or Ctrl-C; makes no gate decision"),
                       ("wait", "Wait until no supervisor runs this task, then show its status")):
        sub.add_parser(name, help=text).add_argument("task", help="Task id or directory")
    sub.choices["status"].add_argument("--timeline", action="store_true", help="Also list every job and decision")
    for name, text in (("approve", "Approve the pending gate"), ("revise", "Send the stage back with a note"),
                       ("reject", "Stop the task")):
        parser_ = sub.add_parser(name, help=text)
        parser_.add_argument("task")
        parser_.add_argument("--note", default="")
        if name != "reject":
            parser_.add_argument("--risk", choices=RISKS, help="Change the risk tier from here on")
            parser_.add_argument("--timeout", type=int, help="Seconds per CLI job from here on")
        if name == "revise":
            parser_.add_argument("--accept-recommendations", action="store_true",
                                 help="At a gate with questions: take the reviewer's recommendation for each "
                                      "question the note does not answer as 'Qn: ...' (critical ones excepted)")
    research = sub.add_parser("research", help="Answer the research gate with a brief")
    research.add_argument("task")
    research.add_argument("--brief", required=True)
    retry = sub.add_parser("retry", help="Retry the blocked job after inspecting its logs")
    retry.add_argument("task")
    retry.add_argument("--max-calls", type=int, help="Raise the task's model call limit")
    retry.add_argument("--timeout", type=int, help="Seconds per CLI job from here on (e.g. for a long implement)")
    sub.add_parser("list", help="List tasks and what each is waiting for")
    sub.add_parser("graph", help="Print the flow graph as Mermaid")
    for name in DETACHABLE:
        sub.choices[name].add_argument(
            "--detach", action="store_true",
            help="Run the supervisor in its own session and follow its log; if this command is killed, the "
                 "work continues: see run_flow.py wait <task>")
    args = parser.parse_args(argv)
    if args.command == "start":
        if args.auto_approve and not args.demo:
            parser.error("--auto-approve is only allowed with --demo")
        if not args.demo and not (args.request and args.repo):
            parser.error("start needs --request and --repo, or --demo")
    if getattr(args, "max_calls", None) is not None and args.max_calls <= 0:
        parser.error("--max-calls must be positive")
    if args.command in ("approve", "revise", "retry") and args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.command == "revise" and not (args.note.strip() or args.accept_recommendations):
        parser.error("revise needs --note, or --accept-recommendations at a gate with questions")
    return args


def task_dir(root, value):
    path = Path(value)
    return path if path.is_dir() else root / "tasks" / value


def show(task, snapshot, details=False, timeline=False):
    values = snapshot.values
    print(f"task {task.id}: risk {values.get('risk', '?')}, model calls "
          f"{task.state.calls()}/{values.get('max_calls') or task.settings['max_calls']}", flush=True)
    for line in (progress.describe(task, values) if details else []) + (
            progress.timeline(task, values) if timeline else []):
        print(line)
    if snapshot.interrupts:
        gate = snapshot.interrupts[0].value
        print(f"awaiting human ({gate['kind']}): {task.directory / gate['summary']}")
        print(f"actions: {', '.join(gate['actions'])}")
        return 2
    if snapshot.next:
        owner = progress.supervisor(task.directory)
        if owner and owner["pid"] != os.getpid():
            print(f"running: {', '.join(snapshot.next)}; wait with: run_flow.py wait {task.id}")
            return 3
        print(f"stopped before {', '.join(snapshot.next)}; continue with: run_flow.py resume {task.id}")
        return 1
    print(f"finished: {values.get('status')}; report: {task.directory / 'report.md'}")
    return 0 if values.get("status") == "approved" else 1


def state_text(snapshot, running=False):
    if snapshot.interrupts:
        return f"awaiting {snapshot.interrupts[0].value['kind']}"
    if snapshot.next:
        return f"{'running' if running else 'stopped before'} {', '.join(snapshot.next)}"
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
        rows.append(f"{task.id}  {task.settings.get('kind', 'code'):<7}  "
                    f"{snapshot.values.get('risk') or task.settings['risk'] or '?':<2}  "
                    f"{state_text(snapshot, bool(progress.supervisor(task.directory))):<26}  {title[:70]}")
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
            research_skills=args.research_skill, rule_paths=args.rules, skill_names=args.skill, kind=args.kind)
        print(directory, flush=True)
    else:
        directory = task_dir(root, args.task)
    task = flow_task.load(root, directory)
    if args.command == "start":
        print(f"kind: {task.settings['kind']}")
        print("rules: " + (", ".join(rule["source"] for rule in task.rules) or "none"))
        print("task skills: " + (", ".join(f"{s['name']} ({s['source']})" for s in task.settings["skills"]) or "none"))
        if task.settings["skill_scripts"]:
            print("skill scripts (implement only): " + ", ".join(task.settings["skill_scripts"]))
        sys.stdout.flush()
    try:
        if args.command == "status":
            return show(task, await flow_task.advance(task, invoke=False), details=True, timeline=args.timeline)
        if args.command == "wait":
            while progress.supervisor(task.directory):
                await asyncio.sleep(2)
            return show(task, await flow_task.advance(task, invoke=False), details=True)
        if args.command != "start":
            await flow_task.check_versions(task)
        with run_lock(task.directory), progress.supervising(task.directory, args.command):
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
            if args.command in ("approve", "revise", "retry") and args.timeout:
                decision["timeout"] = args.timeout
            if getattr(args, "accept_recommendations", False):
                decision["accept"] = True
            return show(task, await flow_task.advance(task, Command(resume=decision)))
    finally:
        task.close()


async def main(args):
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    return await run(args)


def spawn_detached(argv, log):
    """Start `run_flow.py argv` in a new session, writing to `log` (never to our pipes, which die with us)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *argv], cwd=runtime.ROOT,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)


def follow(proc, log, interval=0.5):
    """Copy the child's log to stdout until it exits and return its exit code."""
    with log.open("rb") as source:
        while True:
            chunk = source.read()
            if chunk:
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
            elif proc.poll() is not None:
                sys.stdout.buffer.write(source.read())
                sys.stdout.flush()
                return proc.returncode
            else:
                time.sleep(interval)


def detach(argv):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = runtime.ROOT / "tasks" / "supervisor-logs" / f"{stamp}-{argv[0]}-{os.getpid()}.log"
    proc = spawn_detached([a for a in argv if a != "--detach"], log)
    # stderr keeps the first stdout line of `start` the task directory, as without --detach.
    print(f"supervisor pid {proc.pid} runs detached; log: {log}", file=sys.stderr, flush=True)
    try:
        return follow(proc, log)
    except KeyboardInterrupt:
        print(f"Stopped following; supervisor pid {proc.pid} keeps running. Then: run_flow.py wait <task>",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    args = arguments()
    if getattr(args, "detach", False):
        sys.exit(detach(sys.argv[1:]))
    try:
        sys.exit(asyncio.run(main(args)))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted; inspect job manifests, then: run_flow.py resume <task>", file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Flow error: {exc}", file=sys.stderr)
        sys.exit(1)
