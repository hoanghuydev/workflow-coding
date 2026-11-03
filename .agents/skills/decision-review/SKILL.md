---
name: decision-review
description: Review a material design, UX, API, data-model or permission decision before implementing it - separate goal from proposed solution, check decision-changing premises, compare genuinely different mechanisms, and set acceptance criteria. Use when a non-trivial choice is still open, the request asserts an unverified premise, or the user proposes a specific solution to a broader problem. Not for small, clear, already-decided edits.
---

# Decision review

Goal: pick a defensible approach quickly, with the evidence that matters. This workflow does not grant permission to widen scope, change product policy, or delay a small task with ceremony.

If the user has fully specified a small reversible edit, do it directly with an appropriate existing check. Do not force this workflow, alternatives, or another approval round onto that task.

## 1. Frame the problem (B08, C19, C20)

Write, briefly:
- **Outcome**: what the end user is trying to achieve, and the current obstacle.
- **Proposed solution**: what the user suggested — a hypothesis unless they locked it explicitly.
- **Constraints** tagged with their source: Must / Should / Could / Must-not. Do not promote an example ("có thể thêm…") to a requirement, or demote an explicit requirement to a preference.
- **Acceptance criteria** observable from outside the implementation, defined now so the implementation cannot redefine success. Include the most relevant prohibited outcome for consequential behaviour.

Template: [references/templates.md#spec-card](references/templates.md#spec-card).

## 2. Check decision-changing premises (A01, A02, A04)

List only premises that could flip the decision. Verify each from code, contract, docs, data or a small reversible experiment; mark `✔ verified (where)` or `? unverified (how to check)`. Unverified is not false. If a premise is contradicted, say so with the evidence before proceeding. If a required fact cannot be obtained, give a conditional recommendation and the exact check needed.

## 3. Compare approaches only when the choice is material (A03, B07, B10, B14)

- **Before the first implementation edit**, while the mechanism is still open, consider at least one viable alternative with a **different mechanism or layer** (UI, API, data model, permission model, process), plus keeping current behaviour when relevant, because variants of the suggested mechanism leave the real choice unexamined. One sentence is enough; then proceed. Do not manufacture options for a settled detail, reopen a form the user explicitly locked, or build an alternative just to complete the comparison.
- Eliminate options that violate a Must/Must-not first. Never trade away a binding constraint for convenience.
- Compare the rest on the same criteria: correctness/scope, end-to-end user effort and recoverability, implementation effort, compatibility, maintenance. Name the real downsides of the recommendation.
- For UX, walk through a typical journey and one scale or restricted-access case; optimise task completion and error recovery, not click counts alone. (B09, B13)
- Each new abstraction or dependency needs a current need. (B11, D23)

Template: [references/templates.md#option-matrix](references/templates.md#option-matrix).

## 4. Challenge the choice, then proceed (A06, D24, D25)

- Look for one plausible counterexample or condition under which the recommendation fails. Use evidence independent of your original rationale; another model agreeing is not proof.
- Proceed within the authorised task once decisive premises are checked and the remaining uncertainty is acceptable for a reversible step. Prefer a small spike over another round of analysis.

## Output

Return the decision, the evidence that mattered (with `[đã đọc]`/`[đã chạy]`/`[suy luận]` labels on important claims), the relevant trade-off, and any actual open condition. The different-mechanism comparison above can be one sentence; no mandatory matrix or section headings. Do not dump the whole deliberation or ask for repeated plan approvals.
