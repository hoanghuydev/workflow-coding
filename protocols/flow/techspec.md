# Write or revise the technical spec

Read the repository first: its structure, conventions and tests. Design within
the binding rules. Return the techspec schema. Choose the simplest design
that satisfies the PRD at the stated risk tier and reuse existing modules before
adding new ones. Name concrete files. List the invariants that must never break;
for payment work this includes idempotency, no double credit or debit, an unknown
balance never authorizing a debit, and merchant isolation, when relevant. List
failure modes with their handling.

Map every acceptance criterion to at least one test_plan entry through covers,
preferring automated tests at the lowest level that proves the behaviour. Break
the work into tasks with files. Do not modify files. Do not invent APIs, library
behaviour or infrastructure you have not seen; record such gaps in open_questions.

Resolve findings_to_resolve as in the PRD protocol: one resolution per finding
ID, fixed or rejected with a concrete reason; human findings must be fixed.
