# Access-control changes

Use this reference when changing authorization, role semantics, account scope, or data visibility. It does not define the product's real policy: establish that from the current contract and authoritative implementation first.

## Discover the invariant

Trace identity, tenant, role/action permissions, resource scope, and policy enforcement at the server. Check whether assignment rights differ from the right being assigned. Identify relevant list, detail, export, aggregate, bulk, cache, and background paths; investigate those actually touched by the change.

Write the core invariant in product terms, for example: an actor can assign or read only the resources allowed by the effective policy. The correct policy might include organization-wide access, explicit scope, or inheritance; do not invent a universal rule from the role's name.

## Operation scope and enforcement

Establish the intended resource set, including how membership changes over time. Preserve that meaning in API payloads, execution and user feedback.

Check server-side validation at commit time rather than relying solely on a list filtered earlier. Determine the documented behavior for unauthorized items in a batch: atomic rejection or explicit partial results. Preserve that contract; do not assume HTTP 200 means all items succeeded.

When relevant, cover these cases with appropriate existing or new checks:

- The permitted actor and resource succeed.
- A permitted actor cannot access a resource outside scope or a different tenant.
- A role without the required action cannot use the endpoint.
- Empty, duplicate, stale, or unauthorized selections follow the defined contract.
- Revocation or scope changes between selection and save are enforced.
- Resource resolution does not silently widen the intended operation scope.
- Repeated or interrupted writes do not create unintended duplicate effects.
- Other affected roles, older clients, or shared callers retain expected behavior.

Do not weaken authorization to evade the contract. If policy semantics genuinely change, connect that change to an explicit requirement and verify dependent behavior.

Use synthetic fixtures for negative cases; tests do not require access to real customer data. Auditability, cache invalidation, and propagation checks apply when those mechanisms participate in the changed access path.
