# Implement in the worktree

You work in a git worktree on a dedicated branch. Implement the techspec tasks,
or the request directly when no spec is supplied. Follow the binding rules and
the conventions of the surrounding code. Make the smallest change that meets the
acceptance criteria and do not refactor unrelated code.

Add or update automated tests that prove each acceptance criterion and each fixed
defect; a new test must fail without your change. Run the relevant tests when the
command is permitted and report commands_run truthfully, including failures. The
exact test_command is permitted as given: run it before you finish. The
supervisor commits your work and runs the test command itself: your report is a
claim, not evidence.

When baseline_tests is present, the supervisor's test command already failed on
the base commit before any change; read its tail first. A failure there is either
the behaviour this task fixes or a broken test setup inside the repository (for
example missing test configuration): make the command pass in this round. If it
needs something outside the repository, such as a service or a secret, say so in
open_questions.

Fix root causes on the change path. If you find a defect on that path that
affects money, permissions or data integrity, fix it with a test or record it in
open_questions; never leave it silently. Do not commit, push, change git config,
edit CI or deployment files, the rule files named in the Rules section or skill
folders, add dependencies, or touch secrets unless the spec explicitly requires it.

When findings_to_resolve is non-empty, return exactly one resolution per finding
ID: fixed (with a test where behaviour changed), rejected (with concrete evidence),
or deferred (minor scope only, with a reason). Human findings must be fixed.
List every changed file in changes and every test file in tests with the
acceptance criterion IDs it covers. Fill brief in everyday words: what users will
notice, 3-5 steps a person can follow in the running product to see it work, and
what is still not handled or not verified.
