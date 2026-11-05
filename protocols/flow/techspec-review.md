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
