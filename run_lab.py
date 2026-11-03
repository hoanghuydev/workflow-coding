"""Command line entry point. Default execution calls real models; --demo is offline."""
import argparse
import asyncio
from pathlib import Path
import signal
import sys

from lab import pipeline, runtime


def arguments():
    parser = argparse.ArgumentParser(description="SePay Lab: research, audit, blind review, adjudication and synthesis")
    parser.add_argument("--brief", help="Locked brief with Source <ID> sections (default: inputs/brief.md)")
    parser.add_argument("--rubric", help="Review rubric Markdown (default: config/review-rubric.md)")
    parser.add_argument("--research-skill", action="append", default=[], help="Installed skill to inline for all researchers; repeatable")
    parser.add_argument("--timeout", type=int, default=600, help="Seconds per CLI job, not a money cap (default: 600)")
    parser.add_argument("--max-calls", type=int, help="Maximum started calls, including retries (default: 13)")
    parser.add_argument("--check", action="store_true", help="Check inputs, skills and CLI versions; no inference")
    parser.add_argument("--demo", action="store_true", help="Run the full pipeline with synthetic CLIs, offline")
    parser.add_argument("--resume", type=Path, help="Continue a sealed run; completed jobs are hash-checked and reused")
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry failed/interrupted jobs after inspection; requires --resume")
    parser.add_argument("--revalidate", action="store_true", help="Reparse failed saved outputs locally before continuing pending jobs; requires --resume")
    parser.add_argument("--collect-only", action="store_true", help="Legacy three-CLI collection fixture; no audit or review")
    args = parser.parse_args()
    if args.max_calls is not None and args.max_calls <= 0:
        parser.error("--max-calls must be positive")
    if args.retry_failed and not args.resume:
        parser.error("--retry-failed requires --resume")
    if args.revalidate and not args.resume:
        parser.error("--revalidate requires --resume")
    if args.resume and (args.brief or args.rubric or args.demo or args.research_skill or args.collect_only):
        parser.error("--resume uses sealed inputs; do not combine it with new brief, rubric, demo, skills or collect-only")
    if args.collect_only and (args.demo or args.rubric or args.research_skill):
        parser.error("--collect-only does not support demo, rubric or skills")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


async def main(args):
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    if args.collect_only:
        runtime.BRIEF, runtime.TIMEOUT = args.brief or "inputs/brief.md", args.timeout
        return await runtime.main(check_only=args.check)
    if args.resume:
        if args.check:
            prepared = pipeline.load_sealed(args.resume.resolve())
            current = await pipeline.versions(prepared["config"])
            if current != runtime.read_json(args.resume / "snapshots/versions.json"):
                raise ValueError("CLI versions changed since the sealed run")
            print("Sealed inputs and CLI versions OK; no inference")
            return 0
        return await pipeline.run(runtime.ROOT, resume=args.resume, retry_failed=args.retry_failed,
                                  max_calls=args.max_calls, revalidate=args.revalidate)
    prepared = pipeline.prepare(runtime.ROOT, args.brief or "inputs/brief.md", args.timeout,
                                args.max_calls or pipeline.DEFAULT_CALLS, args.demo, args.research_skill, args.rubric)
    if args.check:
        current = await pipeline.versions(prepared["config"])
        for worker, version in current.items():
            cfg = prepared["config"][worker]
            print(worker, version, cfg["model"], cfg.get("effort"))
        print(f"{len(prepared['skills_lock']['skills'])} installed skills; {len(prepared['sources'])} locked sources")
        print("Plan: 3 research + 3 audit + 3 blind review + 3 adjudication + 1 synthesis")
        print(f"Call limit: {prepared['settings']['max_calls']}; preflight OK; no inference")
        return 0
    return await pipeline.run(runtime.ROOT, prepared)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main(arguments())))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted; inspect manifests before --resume or --retry-failed", file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Lab error: {exc}", file=sys.stderr)
        sys.exit(1)
