# Triage a work request

Read the task request and, where useful, the repository worktree. Return the
triage schema. Classify risk by consequence, not by system name:

- P0: money movement or payment state, idempotency, reconciliation, refunds,
  authentication, authorization, merchant data isolation.
- P1: production operations and integrations: deploys, migrations, timeouts,
  gateway or route configuration, notification delivery.
- P2: ordinary business features: lists, filters, dashboards, forms, exports.
- P3: experiments and demos with no production data path.

When unsure between two tiers choose the more severe one and say why. The
supervisor never lowers the operator's tier. Set needs_research only when a
decision depends on external facts that neither the request nor the repository
can settle, and list those questions; do not research them yourself. Record
ambiguities as open_questions instead of guessing.
