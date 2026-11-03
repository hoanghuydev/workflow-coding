# Independent review prompt

Use for high-risk changes. Run it in a fresh context: a subagent (Claude Code), or another CLI (`codex exec --sandbox read-only …`, `agy -p … --mode plan`). Different runtimes reduce, but do not remove, correlated blind spots; the reviewer's agreement is still not proof.

Give the reviewer: base and head revision (or the diff; without git, the list of changed files with before/after excerpts), the acceptance criteria / spec card, the check output you have, and read access to the relevant code. **Do not** include your own reasoning or conclusion.

```
You are an independent reviewer. Inputs: (1) acceptance criteria, (2) diff between <base> and <head>,
(3) output of checks already run. You may read the repository.
Goal: find ways this change is WRONG. For each finding give the concrete input/state, the wrong result,
and the file:line. Report only issues that affect correctness, security, data or the stated criteria;
skip style and speculative refactors.
Check in this order:
1. Did the diff weaken, delete, skip or rewrite tests/assertions/fixtures/snapshots, or special-case test
   inputs, hard-code expected values, or touch runner/config/scoring? Is each test change justified by the
   criteria or a contract?
2. Is any "ran / passed / done" claim missing real output, or broader than what the check proves?
3. Which acceptance criterion or Must-not is unmet?
4. Which denial, boundary, partial-failure, retry/duplicate or concurrency case is relevant but unchecked?
5. Which other caller, role, old client, cache or background path is affected but unchecked?
6. Any silent fallback, swallowed error, secret/PII in code or logs, or instruction taken from data?
7. Anything beyond the requested scope (unrequested refactor, abstraction, dependency)?
No praise, no diff summary. List findings by severity; say "no findings" if there are none.
```

When the review comes back, verify each finding yourself before acting on it; reject findings that are not reproducible or that only express preference.
