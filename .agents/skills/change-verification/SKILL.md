---
name: change-verification
description: Diagnose a defect or verify a non-trivial behavioural change using the contract, failure cases, blast radius and real execution evidence before reporting it done. Use when debugging, when changing permissions/auth, money or transaction flows, reconciliation, webhooks, data access, migrations or shared code, or before claiming a fix works (vd "sửa lỗi", "đối soát", "webhook", "phân quyền", "migration"). Not needed for typo/text edits that existing checks already cover.
---

# Change verification

Establish what the current change actually proves. This workflow does not authorise production access, deployment, real payment calls, or unrelated refactoring.

Scale the workflow to the actual consequence. A low-consequence, fully specified, reversible edit uses an existing suitable check and a short result; it does not need independent review or this full report. A question about existing behaviour alone is not a high-risk change.

## 1. Know what "correct" means first (D22, D24, E30)

- Read the entry points, contract, implementation and existing checks; identify callers and invariants that the change touches.
- Write the acceptance criteria as observable behaviour, independent of the code you are about to write. Choose depth by consequence, not by edit size: a one-line permission or money change is high risk; a typo in a payments doc is not.
- Permissions, roles, account scope or data visibility: read [references/access-control.md](references/access-control.md). Skip it otherwise.

## 2. Debug with discriminating evidence (B12, E27, G42, G45)

- Reproduce the failure, or gather input/state/log evidence that locates the failing boundary. State a hypothesis a small experiment can distinguish from a competing one; inspect the **first** relevant mismatch.
- Do not stack bypasses, retries, broad `try/catch`, or default return values that hide the failure. A fallback is acceptable only when the contract defines it, it is visible (logged/returned as degraded), and you say so.
- Urgent and authorised mitigation: apply it with its limits and the still-open cause stated. Never report a mitigation as a confirmed root-cause fix.
- Same approach failed twice with no new information: stop and re-diagnose, or ask.

## 3. Implement and verify proportionately (E26, E28, E31)

Select the checks that the contract and side effects make relevant — not a quota:

- The original failing input and the expected behaviour. Retain a distinguishing regression check for a defect fix, reusing an existing test when suitable, because a one-off assertion does not prevent recurrence. Verify failure before and success after the fix when feasible; otherwise state which evidence is missing. Respect restrictions on test changes.
- Denial: no permission, revoked permission, invalid or empty input; important boundaries (0, 1, many).
- Shared code: other callers, roles, old clients/API versions, caches, background jobs. (E28)
- Writes: partial failure, timeout, retry, duplicate request (idempotency), concurrency — when the contract exposes them.

Tests are the oracle; protect their meaning (E31):
- Do not weaken, delete, skip or rewrite assertions, fixtures or snapshots to get green. If a test appears to contradict the spec, **pause that change and report** the conflict with evidence; continue unaffected work.
- Update a test only when an independent requirement or contract justifies it and the change is within the task's scope; respect any explicit "do not modify tests" instruction; keep unrelated assertions intact; say why in the report.
- Gaming is not limited to editing tests: no special-casing test inputs, hard-coding expected values, overloading operators/equality to fool comparisons, tracking call order to pass, or editing runner/config/scoring. (ImpossibleBench §4.1, §5.2)

## 4. Match each claim to its evidence (A05, E29, E30)

- Read actual output, exit status, tool errors and asynchronous status. Build proves compilation; a mock proves local interaction; HTTP 200/exit 0 may only mean "accepted"; reading the target state back proves the side effect in that target. None proves production.
- Ambiguous write (timeout, lost response): check target state or use supported duplicate prevention before retrying. If state cannot be established and duplicates matter (payments, transfers, messages), stop that write and explain.
- Evidence stays valid only while the relevant code/config/environment is unchanged; rerun affected checks after changes, not after every message.

## 5. Review and report

- Inspect the final diff: unintended permission widening, unrelated edits, weakened tests, silent fallbacks, secrets in code/logs, mismatch with user constraints.
- Only an actual high-risk change requires a fresh-context reviewer (subagent or another CLI), using [references/review-prompt.md](references/review-prompt.md). Give diff + criteria + actual check output + read access to code, not your conclusion. Verify each finding yourself. If unavailable, disclose that specific gap.
- Report the result and what the checks prove, with evidence on important claims. Use **Đã xác minh** · **Chưa xác minh** · **Rủi ro còn lại** headings only for a non-small task with an actual unchecked criterion; omit empty sections. Always disclose a relevant failed/unavailable check or concrete supported risk, even in a short answer. Never infer "no remaining risk" from passing tests or an unchanged workspace. When the criteria are met and nothing relevant remains, stop.
