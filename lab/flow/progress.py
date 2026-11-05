"""Plain-text progress for people: is a supervisor running, which job runs now, why rounds
repeated, and a timeline of jobs and gate decisions. Read-only; it never takes the run lock."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .. import runtime
from ..state import now, process_group_alive
from .config import DOC_STAGES
from .contracts import BLOCKING

SUPERVISOR = "supervisor.json"


@contextmanager
def supervising(directory, command):
    """Record the process that holds the run lock so `status`, `list` and `wait` can see it without
    touching the lock (taking it, even briefly, could make a real command fail to start)."""
    path = Path(directory) / SUPERVISOR
    runtime.write_json(path, {"pid": os.getpid(), "command": command, "started_at": now()})
    try:
        yield
    finally:
        try:
            if runtime.read_json(path).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError):
            pass


def supervisor(directory):
    """The live supervisor of a task, or None. A stale file left by a killed process reads as None."""
    path = Path(directory) / SUPERVISOR
    try:
        info = runtime.read_json(path)
        cmdline = Path(f"/proc/{info['pid']}/cmdline").read_bytes()
    except (OSError, ValueError, KeyError):
        return None
    return info if b"run_flow" in cmdline else None


def duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s"


def local(timestamp):
    return datetime.fromisoformat(timestamp).astimezone().strftime("%m-%d %H:%M")


def running(task):
    lines = []
    for row in task.state.history():
        if row["status"] != "running":
            continue
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"])).total_seconds()
        alive = process_group_alive(row["metadata"].get("pid"))
        lines.append(f"  {row['job']} ({row['worker']}) for {duration(elapsed)}"
                     + ("" if alive else ", process gone: interrupted"))
    return lines


def reports(task, pattern):
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((task.directory / "jobs").glob(pattern))]


def review_counts(found):
    blocking = [f for report in found for f in report["findings"] if f["severity"] in BLOCKING]
    asks = sum(1 for f in blocking if f.get("needs_decision"))
    not_met = sum(1 for report in found for a in report.get("acceptance", []) if a["status"] == "not_met")
    text = f"{len(blocking)} blocker/major" + (f" ({asks} need a person)" if asks else "")
    return text + (f", {not_met} criteria not met" if not_met else "")


def rounds(task, values):
    """One line per document and implement round, so a person sees why the flow looped."""
    lines = []
    baseline = values.get("baseline")
    if baseline:
        lines.append(f"  baseline tests on the base commit: {baseline['status']}")
    for doc in DOC_STAGES:
        for round_ in range(1, (values.get(f"{doc}_round") or 0) + 1):
            found = reports(task, f"{doc}-review-*-{round_}/*/report.json")
            lines.append(f"  {doc} r{round_}: " + (f"review {review_counts(found)}" if found else "not reviewed yet"))
    for round_ in range(1, (values.get("impl_round") or 0) + 1):
        path = task.directory / "tests" / f"round-{round_}.json"
        tests = runtime.read_json(path)["status"] if path.is_file() else "not run yet"
        found = reports(task, f"code-review-*-{round_}/*/report.json")
        review = (f"review {review_counts(found)}" if found
                  else "review skipped (tests failed)" if tests in {"failed", "timeout", "error"} else "not reviewed yet")
        lines.append(f"  implement r{round_}: tests {tests}; {review}")
    for decision in values.get("decisions", []):
        note = f": {decision['note'][:100]}" if decision.get("note") else ""
        lines.append(f"  {local(decision['at'])} you: {decision['gate']} -> {decision['action']}{note}")
    return lines


def describe(task, values):
    owner = supervisor(task.directory)
    lines = [f"supervisor: running ({owner['command']}, pid {owner['pid']})" if owner else "supervisor: not running"]
    active = running(task)
    if active:
        lines += ["running now:", *active]
    steps = rounds(task, values)
    if steps:
        lines += ["progress:", *steps]
    return lines


def timeline(task, values):
    events = []
    for row in task.state.history():
        meta = row["metadata"]
        end = datetime.fromisoformat(row["updated_at"])
        seconds = meta.get("duration_seconds")
        start = end.timestamp() - (seconds or 0)
        took = duration(seconds) if seconds is not None else "-"
        attempt = f", attempt {row['attempts']}" if row["attempts"] > 1 else ""
        error = f" {meta['error']}" if meta.get("error") else ""
        events.append((start, f"  {datetime.fromtimestamp(start).strftime('%m-%d %H:%M')}  {row['job']:<48} "
                              f"{row['worker']:<11} {took:>7}  {row['status']}{error}{attempt}"))
    for decision in values.get("decisions", []):
        at = datetime.fromisoformat(decision["at"])
        events.append((at.timestamp(), f"  {local(decision['at'])}  [you] {decision['gate']} -> {decision['action']}"))
    return ["timeline:", *[text for _, text in sorted(events)]] if events else []
