#!/usr/bin/env python3
"""End-of-turn audit for the lab operator: the assistant a person chats with in this repo.

Each CLI's Stop hook runs `python3 hooks/stop_audit.py <claude|codex|agy>` with the hook
payload on stdin. A model from the other provider reads a private copy of the operator's
transcript and answers ok / not ok. "Not ok" blocks the stop once, and the reason becomes
the operator's next instruction. Standard library only: it runs on the system python3.

Never audited:
- lab workers: lab/runtime.py sets SEPAY_LAB_WORKER=1 on every CLI it starts, and the
  auditor inherits the same flag, so it cannot audit itself;
- a turn this hook has already continued once (stop_hook_active; executionNum > 0 for agy);
- any session started with SEPAY_LAB_STOP_AUDIT=off.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PROMPT = Path(__file__).with_name("stop-audit.md")
AUDITOR = {"claude": "codex", "codex": "claude", "agy": "claude"}  # operator runtime -> auditor CLI
# Chosen for auditing, separately from the worker models in config/agents.local.json.
MODELS = {"claude": ("claude-opus-5-5", "medium"), "codex": ("gpt-6.1-sol", "medium")}
AUDIT_TIMEOUT = 420  # seconds; the hook timeout in each CLI's config is 480
WORKER_FLAG = "SEPAY_LAB_WORKER"
SWITCH = "SEPAY_LAB_STOP_AUDIT"
STATE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sepay-lab-stop-audit"
MAX_LAST_MESSAGE = 20000  # characters of the operator's final reply passed inline; the tail is kept
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok", "reason"],
          "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}}}
NOT_FROM_USER = "This message comes from the automatic end-of-turn audit hook, not from the user. "


def read_turn(runtime, payload):
    """Normalise the three Stop payloads. Antigravity uses camelCase and counts continuations."""
    if runtime == "agy":
        return {"transcript": payload.get("transcriptPath"), "last_assistant_message": None,
                "last_user_input": payload.get("lastUserInput"), "session": payload.get("conversationId"),
                "continued": (payload.get("executionNum") or 0) > 0,
                "background_running": payload.get("fullyIdle") is False,
                "finished": payload.get("terminationReason", "NO_TOOL_CALL") == "NO_TOOL_CALL"}
    return {"transcript": payload.get("transcript_path"),
            "last_assistant_message": payload.get("last_assistant_message"),
            "last_user_input": None, "session": payload.get("session_id"),
            "continued": bool(payload.get("stop_hook_active")),
            "background_running": bool(payload.get("background_tasks")), "finished": True}


def state_dir():
    """Per-user folder, readable only by its owner: it briefly holds transcript copies."""
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    return STATE


def error_marker(turn):
    key = hashlib.sha256(str(turn["session"]).encode()).hexdigest()[:32]
    return STATE / f"error-reported-{key}"


def decide(runtime, payload, environ, audit):
    """Return (reason to block, or None to let the operator stop; outcome for the log)."""
    if environ.get(WORKER_FLAG) == "1":
        return None, "skip_worker"
    if environ.get(SWITCH, "").lower() == "off":
        return None, "skip_off"
    turn = read_turn(runtime, payload)
    if not turn["finished"]:
        return None, "skip_unfinished"
    if turn["continued"]:
        return None, "continued"
    marker = error_marker(turn)
    try:
        verdict = audit(runtime, turn)
    except Exception as exc:
        # Report a failing audit once per session; later failures only go to the log.
        if marker.exists():
            return None, "error_repeat"
        state_dir()
        marker.touch()
        return (NOT_FROM_USER + f"The audit could not run ({type(exc).__name__}: {str(exc)[:300]}). "
                "Tell the user in one line that this turn was not independently audited, and that "
                f"further audit failures in this session are only logged in {STATE / 'audit.log'}."), "error"
    marker.unlink(missing_ok=True)
    if verdict["ok"]:
        return None, "ok"
    return (NOT_FROM_USER + "An auditor from another provider flagged your last turn. For each item, fix it, "
            "or tell the user plainly why it is not an error. When you reply, say that the "
            "automatic auditor raised it:\n" + verdict["reason"]), "block"


def cli_prefix(name):
    """CLI path from this machine's config/agents.local.json, else from PATH."""
    try:
        return json.loads((ROOT / "config/agents.local.json").read_text(encoding="utf-8-sig"))[name]["prefix"]
    except (OSError, ValueError, KeyError, TypeError):
        found = shutil.which(name)
        if not found:
            raise FileNotFoundError(f"{name} CLI not found")
        return [found]


def auditor_args(auditor, work):
    model, effort = MODELS[auditor]
    if auditor == "codex":
        # The read-only sandbox blocks writes and network, but not reads outside `work`.
        (work / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        return ["exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "-c", 'approval_policy="never"', "-c", "project_doc_max_bytes=0",
                "-c", "model_reasoning_effort=" + json.dumps(effort),
                "--output-schema", str(work / "schema.json"), "-o", str(work / "verdict.json"),
                "--model", model, "-"]
    # --restricted confines Read/Grep to the working directory, which holds only the transcript copy.
    return ["-p", "Audit the operator turn described on stdin.", "--output-format", "json",
            "--json-schema", json.dumps(SCHEMA, separators=(",", ":")), "--restricted",
            "--permission-mode", "dontAsk", "--tools", "Read,Grep", "--allowedTools", "Read", "Grep",
            "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence", "--disable-slash-commands", "--model", model, "--effort", effort]


def kill_tree(proc):
    """The codex prefix is a Node wrapper around a native binary, so kill the whole group."""
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.communicate(timeout=5)  # reap and close the pipes
    except Exception:
        pass


def run_command(argv, prompt, work):
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", cwd=work, env={**os.environ, WORKER_FLAG: "1"},
                            start_new_session=os.name != "nt")
    previous = signal.getsignal(signal.SIGTERM)

    def on_term(signum, frame):  # the host CLI gave up on the hook: take the auditor down too
        kill_tree(proc)
        sys.exit(1)

    signal.signal(signal.SIGTERM, on_term)
    try:
        stdout, stderr = proc.communicate(prompt, timeout=AUDIT_TIMEOUT)
    except BaseException:
        kill_tree(proc)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)
    return proc.returncode, stdout, stderr


def run_audit(runtime, turn):
    """Run the other provider's CLI on a private copy of the transcript; return {"ok", "reason"}."""
    if not turn["transcript"]:
        raise FileNotFoundError("the hook payload has no transcript path")
    source = Path(turn["transcript"])
    if not source.is_file():
        raise FileNotFoundError(f"transcript not found: {source}")
    auditor = AUDITOR[runtime]
    prefix = cli_prefix(auditor)
    last = turn["last_assistant_message"] or ""
    if len(last) > MAX_LAST_MESSAGE:
        last = f"[first {len(last) - MAX_LAST_MESSAGE} characters omitted]\n" + last[-MAX_LAST_MESSAGE:]
    with tempfile.TemporaryDirectory(dir=state_dir()) as folder:  # deleted after the audit
        work = Path(folder)
        shutil.copyfile(source, work / "transcript.jsonl")
        context = {"operator_runtime": runtime, "transcript_file": "transcript.jsonl (current directory)",
                   "last_assistant_message": last or None, "last_user_input": turn["last_user_input"],
                   "background_tasks_still_running": turn["background_running"]}
        prompt = PROMPT.read_text(encoding="utf-8") + "\n\n" + json.dumps(context, ensure_ascii=False, indent=2)
        code, stdout, stderr = run_command([*prefix, *auditor_args(auditor, work)], prompt, work)
        if code != 0:
            raise RuntimeError(f"{auditor} exited {code}: {stderr.strip()[-300:]}")
        if auditor == "codex":
            verdict = json.loads((work / "verdict.json").read_text(encoding="utf-8"))
        else:
            envelope = json.loads(stdout)
            if envelope.get("is_error") or envelope.get("subtype") != "success":
                raise RuntimeError(f"claude returned {envelope.get('subtype')}")
            verdict = envelope.get("structured_output")
    if not (isinstance(verdict, dict) and isinstance(verdict.get("ok"), bool)
            and isinstance(verdict.get("reason"), str)):
        raise ValueError("auditor returned no valid verdict")
    return verdict


def log(runtime, outcome, seconds):
    """Outcome and timing only: reasons can quote the conversation, so they stay out of the log."""
    try:
        with (state_dir() / "audit.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "runtime": runtime,
                                     "outcome": outcome, "seconds": round(seconds, 1)}) + "\n")
    except OSError:
        pass


def main(argv=None, stdin=None, stdout=None, environ=None, audit=run_audit):
    argv = sys.argv[1:] if argv is None else argv
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    environ = os.environ if environ is None else environ
    runtime = argv[0] if argv else ""
    if runtime not in AUDITOR:
        print(f"usage: stop_audit.py {{{'|'.join(AUDITOR)}}}", file=sys.stderr)
        return 0  # a misconfigured hook must not trap the operator
    started = time.monotonic()
    try:
        payload = json.loads(stdin.read() or "{}")
        reason, outcome = decide(runtime, payload, environ, audit)
    except Exception as exc:  # unreadable payload: the loop state is unknown, so never block
        reason, outcome = None, f"hook_error: {type(exc).__name__}"
    if reason is not None:
        decision = "continue" if runtime == "agy" else "block"
        stdout.write(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False) + "\n")
    elif runtime == "agy":
        stdout.write(json.dumps({"decision": "stop"}) + "\n")  # anything but "continue" lets agy stop
    log(runtime, outcome, time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
