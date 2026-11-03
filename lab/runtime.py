import asyncio
from contextlib import closing
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from uuid import uuid4

from jsonschema import validate
from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 180  # seconds per worker; not a dollar spending cap
BRIEF = "inputs/brief.md"  # relative to ROOT; overridable with --brief
MAX_OUTPUT = 8 * 1024 * 1024  # bytes per stream; checked periodically


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, obj):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}


def check_agents(config):
    if set(config) != {"codex", "claude", "antigravity"}:
        raise ValueError("Expected exactly three configured workers")
    for name, cfg in config.items():
        if not isinstance(cfg.get("model"), str) or not cfg["model"].strip() or "REPLACE_" in json.dumps(cfg):
            raise ValueError(f"Set exact model/effort for {name} first")
        prefix = cfg.get("prefix")
        if not isinstance(prefix, list) or not prefix or any(not isinstance(p, str) or not Path(p).is_file() for p in prefix):
            raise ValueError(f"Invalid executable prefix for {name}")
        if not os.access(prefix[0], os.X_OK):
            raise ValueError(f"Executable permission missing for {name}")
        if cfg.get("effort") is not None and cfg["effort"] not in EFFORTS:
            raise ValueError(f"Invalid effort for {name}")
    return config


def check_policy(policy_document):
    policy = policy_document.get("permissions", {})
    required_denials = {"write_file(*)", "command(*)", "read_url(*)", "execute_url(*)", "mcp(*)"}
    if not required_denials.issubset(policy.get("deny", [])) or policy.get("allow") != [] or policy.get("ask") != []:
        raise ValueError("Fixture policy must deny writes, commands, browsing and MCP")
    return policy_document


def preflight(config_override=None):
    config = check_agents(config_override if config_override is not None else read_json(ROOT / "config/agents.local.json"))
    schema = read_json(ROOT / "config/report.schema.json")
    validator_for(schema).check_schema(schema)
    policy_document = check_policy(read_json(ROOT / "config/agy-research.json"))
    brief = (ROOT / BRIEF).read_bytes()
    if not re.findall(r"^Source ([A-Za-z][A-Za-z0-9_-]*)\b", brief.decode("utf-8"), re.M):
        raise ValueError("Brief must declare source IDs using 'Source <ID>'")
    return config, schema, policy_document, brief


async def stop_tree(proc):
    if os.name == "nt":
        if proc.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                "/PID", str(proc.pid), "/T", "/F",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await proc.wait()


# Access modes. "packet" is the sealed research mode: the packet is the only input.
# "read" lets the CLI read a repository worktree (cwd) without changing it.
# "write" lets the CLI edit files and run allow-listed commands inside the worktree.
ACCESS_MODES = ("packet", "read", "write")
_SUBMIT = ("Return the required JSON using the CLI's native structured-output mechanism; "
           "a tool used solely to submit that structured result is permitted.\n\n")
PROMPTS = {
    # Supply the complete identical packet inline: reading via a shell would
    # conflict with the fixture's explicit prohibition on running commands.
    "packet": ("Follow the complete assigned input below. Use only this supplied packet. "
               "Do not read files, run commands, browse, use MCP or access other conversations. " + _SUBMIT),
    "read": ("Follow the complete assigned input below. You may read files inside the current working "
             "directory, a git worktree of the target repository, to ground your answer. Do not modify "
             "files, browse, use MCP or access other conversations. " + _SUBMIT),
    "write": ("Follow the complete assigned input below. Work only inside the current working directory, "
              "a git worktree on a dedicated branch. You may edit files there and run local build or test "
              "commands. Do not commit, push, merge, deploy, browse, use MCP, access other conversations "
              "or touch files outside this directory. " + _SUBMIT),
}
# Codex event item types that each access mode must never contain.
FORBIDDEN_CODEX_ITEMS = {
    "packet": {"command_execution", "file_change", "mcp_tool_call", "web_search"},
    "read": {"file_change", "mcp_tool_call", "web_search"},
    "write": {"mcp_tool_call", "web_search"},
}
CLAUDE_TOOLS = {"packet": ["Read"], "read": ["Read", "Grep", "Glob"],
                "write": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]}
CLAUDE_WRITE_BASH = ["Bash(git diff *)", "Bash(git status *)"]


def cli_args(name, cfg, run_dir, work, schema, timeout, access="packet", allow_bash=()):
    if access not in ACCESS_MODES:
        raise ValueError(f"Unknown access mode: {access}")
    model_args = ["--model", cfg["model"]]
    effort = cfg.get("effort")
    schema_path = str(run_dir / "schema.snapshot.json")
    if name == "codex":
        sandbox = "workspace-write" if access == "write" else "read-only"
        args = ["exec", "--ignore-user-config", "--ephemeral", "--json",
                "--skip-git-repo-check", "--sandbox", sandbox,
                "-c", 'approval_policy="never"', "--output-schema", schema_path,
                "-o", str(work / "final.json"), *model_args]
        if effort:
            args += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
        # Rules reach workers only through the sealed packet: never this lab's operator AGENTS.md,
        # nor a target-repo AGENTS.md the implementer may have edited in the worktree.
        return args + ["-c", "project_doc_max_bytes=0", "-"]
    if name == "claude":
        tools = CLAUDE_TOOLS[access]
        allowed = tools if access != "write" else [
            *[t for t in tools if t != "Bash"], *CLAUDE_WRITE_BASH,
            *[rule for command in allow_bash for rule in (f"Bash({command})", f"Bash({command} *)")]]
        args = ["-p", "Follow the complete assigned packet on stdin.", "--output-format", "json",
                "--json-schema", json.dumps(schema, separators=(",", ":")),
                "--permission-mode", "dontAsk", "--tools", ",".join(tools),
                "--allowedTools", *allowed, "--setting-sources", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--no-session-persistence", "--disable-slash-commands", *model_args]
        return args + (["--effort", effort] if effort else [])
    if access == "write":
        # Antigravity write/sandbox flags exist but their enforcement is unverified here.
        raise ValueError("Antigravity write access is not supported; assign write roles to codex or claude")
    args = ["--input-format", "stream-json", "--output-format", "stream-json", "--json-schema", schema_path,
            "--mode", "plan", "--settings", str(run_dir / "agy-policy.snapshot.json"),
            "--disable-slash-commands", "--print-timeout", f"{max(timeout - 10, 1)}s", *model_args]
    return args + (["--effort", effort] if effort else [])


async def worker(name, cfg, run_dir, schema, *, packet=None, validate_output=None,
                 timeout=None, on_started=None, access="packet", cwd=None, allow_bash=()):
    timeout = TIMEOUT if timeout is None else timeout
    args = cli_args(name, cfg, run_dir, run_dir / name, schema, timeout, access, allow_bash)
    work = run_dir / name
    work.mkdir()
    (work / "INPUT.md").write_bytes(packet if packet is not None else (run_dir / "brief.snapshot.md").read_bytes())
    prefix = cfg["prefix"]
    effort = cfg.get("effort")
    prompt = PROMPTS[access] + (work / "INPUT.md").read_text(encoding="utf-8")

    started = time.monotonic()
    meta = {"worker": name, "requested_model": cfg["model"],
            "requested_effort": effort, "effective_model": None,
            "effective_effort": None, "input_sha256": digest(work / "INPUT.md"),
            "status": "running", "cost_usd": None,
            "command": [*prefix, *args]}
    if access != "packet":
        meta.update(access=access, cwd=str(cwd))
    write_json(work / "manifest.json", meta)
    proc = None
    waiting = None
    try:
        opts = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                else {"start_new_session": True})
        with (work / "stdout.log").open("wb") as out, (work / "stderr.log").open("wb") as err:
            # SEPAY_LAB_WORKER marks lab workers so the operator's Stop hook (hooks/stop_audit.py) skips them.
            proc = await asyncio.create_subprocess_exec(
                *prefix, *args, cwd=cwd or work, stdin=subprocess.PIPE,
                stdout=out, stderr=err, env={**os.environ, "SEPAY_LAB_WORKER": "1"}, **opts)
            meta["pid"] = proc.pid
            write_json(work / "manifest.json", meta)
            if on_started:
                on_started(dict(meta))
            stdin_data = (json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
                          if name == "antigravity" else prompt).encode("utf-8")
            waiting = asyncio.create_task(proc.communicate(stdin_data))
            while not waiting.done():
                if time.monotonic() - started > timeout:
                    raise RuntimeError("timeout")
                if any((work / f).exists() and (work / f).stat().st_size > MAX_OUTPUT
                       for f in ("stdout.log", "stderr.log", "final.json")):
                    raise RuntimeError("output_limit")
                await asyncio.sleep(0.2)
            await waiting
            meta["exit_code"] = proc.returncode
        collect_output(name, work, schema, meta,
                       packet if packet is not None else (run_dir / "brief.snapshot.md").read_bytes(),
                       validate_output)
    except asyncio.CancelledError:
        meta["status"] = "interrupted"
        meta["error"] = "cancelled"
        raise
    except Exception as exc:
        meta.update(status="failed", error=str(exc))
    finally:
        if proc is not None:
            try:
                await stop_tree(proc)
            except Exception as exc:
                meta["cleanup_error"] = str(exc)
                meta["status"] = "failed"
        if waiting is not None:
            if not waiting.done():
                waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
        meta["duration_seconds"] = round(time.monotonic() - started, 3)
        write_json(work / "manifest.json", meta)
    return meta


def collect_output(name, work, schema, meta, expected_packet, validate_output=None):
    """Parse saved output without inference; preserve raw provider artifacts."""
    if any((work / f).exists() and (work / f).stat().st_size > MAX_OUTPUT
           for f in ("stdout.log", "stderr.log", "final.json")):
        raise RuntimeError("output_limit")
    if meta["exit_code"] != 0:
        raise RuntimeError("nonzero_exit")
    access = meta.get("access", "packet")
    raw = (work / "stdout.log").read_text(encoding="utf-8-sig")
    if name == "codex":
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if any(e.get("type") in ("turn.failed", "error") for e in events):
            raise RuntimeError("provider_failure")
        done = [e for e in events if e.get("type") == "turn.completed"]
        if not done:
            raise RuntimeError("missing_completion")
        meta["usage"] = done[-1].get("usage")
        meta["provider_session_id"] = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
        if any((e.get("item") or {}).get("type") in FORBIDDEN_CODEX_ITEMS[access] for e in events):
            raise RuntimeError("unexpected_tool_operation")
        report = read_json(work / "final.json")
    else:
        if name == "antigravity":
            events = [json.loads(line) for line in raw.splitlines() if line.strip()]
            results = [e["result"] for e in events if e.get("event") == "result"]
            if len(results) != 1:
                raise RuntimeError("expected_one_provider_result")
            envelope = results[0]
        else:
            envelope = json.loads(raw)
        meta["usage"] = envelope.get("usage")
        meta["provider_session_id"] = envelope.get("conversation_id" if name == "antigravity" else "session_id")
        meta["cost_usd"] = envelope.get("total_cost_usd")
        meta["provider_finished_reason"] = envelope.get("finished_reason")
        if envelope.get("finished_reason") == "print_timeout":
            raise RuntimeError("provider_print_timeout")
        if name == "antigravity" and envelope.get("status") != "SUCCESS":
            raise RuntimeError("provider_failure")
        if name == "claude" and (envelope.get("is_error") or
                                  envelope.get("subtype") != "success"):
            raise RuntimeError("provider_failure")
        report = envelope.get("structured_output")
        if envelope.get("permission_denials"):
            meta["permission_denials"] = envelope["permission_denials"]
            # A coding job may try a disallowed command; the supervisor runs tests itself,
            # so record the denial for reviewers instead of discarding the edits.
            if access != "write":
                raise RuntimeError("permission_diagnostic_requires_review")
        if report is None:
            raise RuntimeError("missing_structured_output")
    validate(report, schema)
    if validate_output is not None:
        validate_output(report)
    else:
        validate_research(report, (work / "INPUT.md").read_text(encoding="utf-8"))
    if (work / "INPUT.md").read_bytes() != expected_packet:
        raise RuntimeError("input_changed")
    diagnostics = (work / "stderr.log").read_text(encoding="utf-8", errors="replace")
    # Conservative flag only: wording can change, so stderr still needs review.
    if re.search(r"denied|permission required|requires approval", diagnostics, re.I):
        if access != "write":
            raise RuntimeError("permission_diagnostic_requires_review")
        meta["stderr_permission_flag"] = True
    write_json(work / "report.json", report)
    meta["report_sha256"] = digest(work / "report.json")
    meta["status"] = "collected_unverified"


def validate_research(report, brief):
    if not report["claims"] or not report["summary"].strip():
        raise RuntimeError("empty_report")
    ids = [c["id"] for c in report["claims"]]
    source_ids = set(re.findall(r"^Source ([A-Za-z][A-Za-z0-9_-]*)\b", brief, re.M))
    if (len(set(ids)) != len(ids) or any(
            not c["id"].strip() or c["id"] in {"summary", "limitations"} or not c["text"].strip()
            or not c["source_ids"] or len(c["source_ids"]) != len(set(c["source_ids"]))
            or not set(c["source_ids"]).issubset(source_ids) for c in report["claims"])):
        raise RuntimeError("invalid_claim_references")


async def main(check_only=False):
    config, schema, policy, brief = preflight()
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name, command in [(n, [*c["prefix"], "--version"]) for n, c in config.items()] + [
            ("node", ["node", "--version"]), ("git", ["git", "--version"])]:
        result = await asyncio.to_thread(subprocess.run, command, check=True,
                                         capture_output=True, text=True, timeout=10)
        versions[name] = result.stdout.strip()
    if check_only:
        for name, cfg in config.items():
            print(name, versions[name], cfg["model"], cfg.get("effort"))
        print("Preflight OK; no inference performed")
        return 0
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True)
    print(run_dir, flush=True)
    write_json(run_dir / "versions.snapshot.json", versions)
    write_json(run_dir / "config.snapshot.json", config)
    write_json(run_dir / "schema.snapshot.json", schema)
    write_json(run_dir / "agy-policy.snapshot.json", policy)
    (run_dir / "brief.snapshot.md").write_bytes(brief)
    tasks = [asyncio.create_task(worker(n, c, run_dir, schema)) for n, c in config.items()]
    cancelled = False
    if os.name != "nt":
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        cancelled = True
        results = await asyncio.gather(*tasks, return_exceptions=True)
    rows = []
    for name, result in zip(config, results):
        if isinstance(result, BaseException):
            manifest = run_dir / name / "manifest.json"
            result = (read_json(manifest) if manifest.is_file() else
                      {"worker": name, "status": "failed", "error": type(result).__name__})
        rows.append(result)
    write_json(run_dir / "results.json", rows)
    with closing(sqlite3.connect(ROOT / "runs/state.db")) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS jobs (run_id TEXT, worker TEXT, metadata TEXT, PRIMARY KEY(run_id, worker))")
        db.executemany("INSERT INTO jobs VALUES (?, ?, ?)",
                       [(run_id, r["worker"], json.dumps(r, ensure_ascii=False)) for r in rows])
    print(run_dir)
    for row in rows:
        print(row["worker"], row["status"], row.get("error", ""))
    if cancelled:
        raise asyncio.CancelledError
    return 0 if all(r["status"] == "collected_unverified" for r in rows) else 1
