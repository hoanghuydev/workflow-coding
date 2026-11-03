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
