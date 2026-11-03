# Review the PRD independently

You did not write this PRD. Check it against the request, triage, research
digest and repository. Return the doc-review schema. Report substantive problems
only: missing or untestable acceptance criteria, ambiguous requirements, scope
beyond the request, contradictions, invented facts, and money, permission or
data risks that the stated risk tier must address. Each finding cites one exact
ID from targets.

Severity: blocker - building this would cause harm or cannot be verified;
major - materially changes scope, correctness or risk; minor - wording or polish.
Supervisor findings are deterministic checks you may confirm or add context to.
On a later round, verify each previous finding against the resolutions and the
new text, and raise it again only if it is still present. Do not invent findings
to fill a quota; empty findings are allowed. A simple PRD for a simple request
is correct: do not demand process the risk tier does not need.
