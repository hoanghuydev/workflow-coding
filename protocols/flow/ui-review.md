# Review the interface change independently

You did not write this change. Check the diff and worktree against the UX spec,
the PRD and the supervisor's test result. Return the code-review schema.

Report substantive problems with user impact: a journey that cannot be completed,
a missing loading, empty, error or permission state, copy that differs from the
spec or misleads, controls without accessible names or keyboard access, focus
lost after an action, and layouts that break on a narrow screen (kinds usability,
accessibility, spec-mismatch). Cite the file and line.

You see code and test output, not a rendered screen. Mark anything that needs a
rendered screen or a real interaction to judge as unverified in limitations and
in acceptance; do not present visual guesses as findings. Same severity scale as
code review. Empty findings are allowed.
