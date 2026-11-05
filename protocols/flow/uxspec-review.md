# Review the UX specification independently

You did not write this spec. Check it against the PRD, the repository's existing
screens and components, and the risk tier. Return the doc-review schema. Report
substantive problems: an acceptance criterion no journey completes, a missing
loading, empty, error or permission state, a dead end without recovery, copy that
misleads, an inaccessible interaction, a layout that breaks on a narrow screen,
and new components where an existing one fits. Each finding cites one exact ID
from targets.

Use the same severity scale and rules as PRD review: blocker, major, minor; no
quota; on later rounds re-raise a finding only if it is still present. Judge
against user impact and the PRD, not personal taste.

Most findings are fixed by the author without asking anyone. Set needs_decision
only for a business or product policy that the request, the rules, the recorded
project decisions and the repository leave open, and on which two reasonable
product owners could choose differently: fees, limits, who may do what, what is
in scope. It is never a decision when one option breaks the request's goal, a
binding rule or an invariant (for example allowing a double write in a task that
exists to stop double writes), or when it concerns correctness, security or data
integrity: raise an ordinary finding. A reversible detail with a sensible
default (a timeout, wording, placement) is not a decision either: ask the author
to record it under assumptions. For a real decision, write reason as the
question in everyday words, list two to four options that are all acceptable,
each with its consequence for users, put your recommendation and why in
suggestion, fill author_choice and agrees_with_author, and set critical when a
wrong choice loses money, exposes data or permissions, or cannot be undone.
Raise at most three decisions; merge related ones. A request or document that
contradicts a recorded project decision is a decision.

Check the brief and the assumptions against the document and the request: a
brief that hides or softens a risk, or an assumption that is really an open
business policy, is a major finding.
