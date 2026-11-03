"""Ledger-guarded model jobs shared by the research pipeline and the work flow.

LangGraph re-executes a whole node after a crash or an interrupt resume, so the
graph checkpoint alone cannot prevent a second paid call. Every model call goes
through JobRunner: a completed job is hash-checked and reused, a failed or
interrupted job blocks until an operator explicitly allows a retry, and the
call limit is checked durably before a process is spawned.
"""
import asyncio
import copy
import hashlib
import shutil
from uuid import uuid4

from . import runtime
from .state import now, process_group_alive


def sha(data):
    return hashlib.sha256(data).hexdigest()


async def gather_all(coroutines):
    """Run jobs concurrently. Cancellation cancels every sibling; an exception (corrupt
    artifact, programming error) is re-raised rather than turned into missing coverage."""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        values = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    for value in values:
        if isinstance(value, BaseException):
            raise value
    return values


class JobRunner:
    def __init__(self, directory, config, policy, state, *, timeout, max_calls,
                 retry_failed=False, revalidate=False):
        self.directory = directory
        self.config = config
        self.policy = policy
        self.state = state
        self.timeout = timeout
        self.max_calls = max_calls
        self.retry_failed = retry_failed
        self.revalidate = revalidate
        self.blockers = []

    async def run(self, job_id, stage, worker, packet, schema, validate, *, cfg=None,
                  access="packet", cwd=None, allow_bash=(), retry=None, before_start=None):
        """Return the validated report, or None after recording a blocker."""
        cfg = cfg or self.config[worker]
        retry = self.retry_failed if retry is None else retry
        runtime.cli_args(worker, cfg, self.directory, self.directory, schema, self.timeout, access)  # fail before counting a call
        base = self.directory / "jobs" / job_id
        self.state.plan(job_id, stage, worker)
        previous = self.state.get(job_id)
        manifest_path = base / worker / "manifest.json"
        manifest = runtime.read_json(manifest_path) if manifest_path.is_file() else None
        report_path = base / worker / "report.json"
        if (self.revalidate and manifest and manifest["status"] == "failed"
                and manifest.get("exit_code") == 0 and manifest.get("input_sha256") == sha(packet)
                and not manifest.get("cleanup_error")
                and not process_group_alive(manifest.get("pid"))):
            original = copy.deepcopy(manifest)
            candidate = copy.deepcopy(manifest)
            try:
                runtime.collect_output(worker, base / worker, schema, candidate, packet, validate)
            except Exception as exc:
                print(f"cached {job_id}: still invalid ({exc})", flush=True)
            else:
                history = self.directory / "revalidations"
                history.mkdir(exist_ok=True)
                runtime.write_json(history / f"{job_id}-{uuid4().hex[:8]}.json", original)
                candidate.pop("error", None)
                candidate["revalidated_at_utc"] = now()
                runtime.write_json(manifest_path, candidate)
                self.state.save(job_id, candidate)
                previous, manifest = self.state.get(job_id), candidate
                print(f"cached {job_id}: revalidated without inference", flush=True)
        if previous["status"] == "collected_unverified" or (manifest and manifest["status"] == "collected_unverified"):
            expected = previous["metadata"] if previous["status"] == "collected_unverified" else manifest
            if not manifest or manifest != expected:
                raise ValueError(f"Completed manifest changed: {job_id}")
            if (manifest["input_sha256"] != sha(packet) or not report_path.is_file()
                    or runtime.digest(report_path) != manifest["report_sha256"]
                    or runtime.digest(base / worker / "INPUT.md") != sha(packet)):
                raise ValueError(f"Completed job artifact changed: {job_id}")
            result = runtime.read_json(report_path)
            validate(result)
            if process_group_alive(manifest.get("pid")):
                raise ValueError(f"Process group still active: {job_id}")
            self.state.save(job_id, manifest)  # Recover a completed manifest after supervisor crash.
            print(f"reuse {job_id}", flush=True)
            return result
        if previous["attempts"]:
            pid = (manifest or {}).get("pid") or previous["metadata"].get("pid")
            if process_group_alive(pid):
                self.blockers.append(f"{job_id}: process group {pid} is still active")
                return None
            if not retry:
                self.blockers.append(f"{job_id}: {previous['status']}; inspect artifacts then use --retry-failed")
                return None
        if self.state.calls() >= self.max_calls:
            self.blockers.append(f"{job_id}: model call limit {self.max_calls} reached")
            return None
        # A retry preserves all prior attempts instead of overwriting diagnostics.
        if base.exists():
            archive = self.directory / "attempts" / f"{job_id}-{previous['attempts']}-{uuid4().hex[:8]}"
            archive.parent.mkdir(exist_ok=True)
            shutil.move(str(base), archive)
        base.mkdir(parents=True)
        runtime.write_json(base / "schema.snapshot.json", schema)
        runtime.write_json(base / "agy-policy.snapshot.json", self.policy)
        if before_start:
            before_start()
        self.state.start(job_id, self.max_calls)  # Durable transition BEFORE subprocess creation.
        print(f"start {job_id}: {worker}", flush=True)
        try:
            meta = await runtime.worker(worker, cfg, base, schema, packet=packet, validate_output=validate,
                                        timeout=self.timeout, access=access, cwd=cwd, allow_bash=allow_bash,
                                        on_started=lambda metadata: self.state.save(job_id, metadata))
        except asyncio.CancelledError:
            if manifest_path.is_file():
                self.state.save(job_id, runtime.read_json(manifest_path))
            raise
        self.state.save(job_id, meta)
        print(f"{job_id}: {meta['status']} {meta.get('error', '')}", flush=True)
        if meta["status"] != "collected_unverified":
            self.blockers.append(f"{job_id}: {meta.get('error', meta['status'])}")
            return None
        return runtime.read_json(report_path)
