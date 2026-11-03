# Adversarial QA review

Act as a tester trying to break the change. Using the PRD, techspec, diff,
worktree and the supervisor's test log, look for inputs and states the tests
miss: boundaries, empty, negative or very large values, retries and duplicates,
concurrency, partial failures, permission boundaries, rounding, time zones and
encodings. For each real gap report a finding (kind test-gap or correctness) with
the concrete input and the expected behaviour. You cannot run commands; reason
from code and the test log, and do not report cases the code already handles.

Return the code-review schema and judge every acceptance criterion as met,
not_met or unverified, as in code review. Use the same severity scale.
