# Review the technical spec independently

You did not write this spec. Check it against the PRD, the repository and the
risk tier, reading the code to verify every claim about existing files, APIs and
behaviour. Return the doc-review schema. Look for designs that do not fit the
existing code, missing failure modes, broken invariants, unsafe data or schema
changes, acceptance criteria without a real test, files or APIs that do not exist,
designs that break a binding rule, and complexity beyond what the tier needs.

Use the same severity scale and rules as PRD review: blocker, major, minor; no
quota; on later rounds re-raise a finding only if it is still present. The right
answer for a small change may be a small spec.
