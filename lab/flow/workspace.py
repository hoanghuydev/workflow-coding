"""Git worktree and test execution owned by the supervisor, not by the models.

Agents edit a dedicated worktree on branch flow/<task-id>. The supervisor
commits each implement round, computes the real diff and runs the configured
test command itself; a model's claim that tests passed is never evidence.
Nothing here merges, pushes or deploys.
"""
import asyncio
import os
import signal
import subprocess
import time

COMMITTER = ["-c", "user.name=sepay-flow", "-c", "user.email=sepay-flow@localhost", "-c", "commit.gpgsign=false"]


def git(cwd, *args, raw=False):
    """Bytes in, lenient text out: target repositories may hold non-UTF-8 files and
    non-ASCII paths (quotePath off keeps them unescaped)."""
    result = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True,
                            timeout=120)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise ValueError(f"git {' '.join(args[:2])} failed: {error}")
    return result.stdout if raw else result.stdout.decode("utf-8", errors="replace")


def paths(output):
    return [path for path in output.split("\0") if path]


def resolve(repo, ref):
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def create_worktree(repo, base_sha, path, branch):
    git(repo, "worktree", "add", "-b", branch, str(path), base_sha)


def head(worktree):
    return git(worktree, "rev-parse", "HEAD").strip()


def dirty(worktree):
    return bool(git(worktree, "status", "--porcelain", "--untracked-files=all").strip())


def archive_and_reset(worktree, archive):
    """Keep a crashed attempt's partial edits as a patch, then restore the last commit."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    git(worktree, "add", "-A")
    archive.write_bytes(git(worktree, "diff", "--cached", "--binary", raw=True))
    git(worktree, "reset", "--hard", "HEAD")
    git(worktree, "clean", "-fd")


def commit_all(worktree, message):
    if not dirty(worktree):
        return None
    git(worktree, "add", "-A")
    git(worktree, *COMMITTER, "commit", "-q", "-m", message)
    return head(worktree)


def changed_files(worktree, base, tip):
    # --no-renames lists both sides of a rename, so either name can be cited.
    return paths(git(worktree, "diff", "--name-only", "--no-renames", "-z", base, tip))


def diff_text(worktree, base, tip, limit):
    text = git(worktree, "diff", "--stat", base, tip) + "\n" + git(worktree, "diff", base, tip)
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    return data[:limit].decode("utf-8", errors="ignore"), True


def known_files(worktree, base, tip):
    """Files a review finding may cite: the current tree plus anything deleted in the diff."""
    return set(paths(git(worktree, "ls-files", "-z"))) | set(changed_files(worktree, base, tip))


def log(worktree, base, tip):
    return git(worktree, "log", "--format=%h %s", f"{base}..{tip}").splitlines()


async def run_tests(worktree, argv, timeout, log_path):
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as out:
        try:
            proc = await asyncio.create_subprocess_exec(*argv, cwd=worktree, stdin=subprocess.DEVNULL,
                                                        stdout=out, stderr=subprocess.STDOUT,
                                                        start_new_session=True)
        except OSError as exc:
            out.write(f"cannot start test command: {exc}\n".encode())
            return {"status": "error", "exit_code": None, "error": str(exc)}
        try:
            await asyncio.wait_for(proc.wait(), timeout)
            status = "passed" if proc.returncode == 0 else "failed"
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            status = "timeout"
    return {"status": status, "exit_code": proc.returncode, "duration_seconds": round(time.monotonic() - started, 3)}


def tail(path, size=4000):
    data = path.read_bytes() if path.is_file() else b""
    return data[-size:].decode("utf-8", errors="replace")
