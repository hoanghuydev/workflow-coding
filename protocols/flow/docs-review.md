# Review the documentation change independently

You did not write these docs. Check the diff against the request, the code in
the worktree and the supervisor's test result. Return the code-review schema.

Report substantive problems: a claim the code contradicts (kind accuracy), a
missing parameter, default, error or prerequisite, an example that cannot work
as written, a procedure that skips a step, and wording that misleads (kind
clarity). Cite the doc file and line. An example counts as verified only if the
supervisor's test ran it; otherwise say it is unverified in limitations. Judge
every acceptance criterion, if any, as met, not_met or unverified.

Severity: blocker - following the docs causes harm or data loss; major - a reader
gets a wrong result or cannot finish the task; minor - style. Empty findings are
allowed.
