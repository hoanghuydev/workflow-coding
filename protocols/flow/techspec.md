# Write or revise the technical spec

Read the repository first: its structure, conventions and tests. Design within
the binding rules. Return the techspec schema. For a defect, give the root cause with the code
path that produces it, not only the symptom. Choose the simplest design
that satisfies the PRD at the stated risk tier and reuse existing modules before
adding new ones. Name concrete files. List the invariants that must never break;
for payment work this includes idempotency, no double credit or debit, an unknown
balance never authorizing a debit, and merchant isolation, when relevant. List
failure modes with their handling.

Map every acceptance criterion to at least one test_plan entry through covers,
preferring automated tests at the lowest level that proves the behaviour. Break
the work into tasks with files. Do not modify files. Do not invent APIs, library
behaviour or infrastructure you have not seen; record such gaps in open_questions.
When a gap is a product or policy choice, list the options and the one you would
choose rather than deciding it silently.

Fill brief in everyday words for people who will not read the rest: what changes
for users, how the main flow will work, what is left out and what could still go
wrong. Record the choices you settled yourself under assumptions with the reason,
and follow the recorded project decisions in the Rules section unless the
request changes them.

Resolve findings_to_resolve as in the PRD protocol: one resolution per finding
ID, fixed or rejected with a concrete reason; human findings must be fixed.
