# Templates — decision-review

Use only the parts that carry information for the task at hand.

## spec-card

```
Outcome (end user): …
Current obstacle: …
Proposed solution (hypothesis unless locked by the user): …

Must:      … (source: …)
Should:    …
Could:     …
Must-not:  … (source: …)

Premises that could flip the decision:
  ✔ … (verified at: file:line / doc / data)
  ? … (unverified → how to check: …)

Acceptance criteria (observable):
  1. …
  2. … (prohibited outcome: …)

Superseded decisions: …
```

## option-matrix

Neutral goal (no solution embedded): …

| Criterion | Option 1 (layer: …) | Option 2 (layer: …) | Keep current |
|---|---|---|---|
| Violates a Must/Must-not? | | | |
| Correctness / least privilege / revocable | | | |
| End-to-end user effort, undo, error recovery | | | |
| Implementation effort | | | |
| Backward compatibility | | | |
| Maintenance | | | |

**Recommendation:** … because … · **Fails if:** …

