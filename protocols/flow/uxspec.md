# Write or revise the UX specification

Return the UX spec schema. Specify how users complete the tasks in the PRD, not
how to build it. Read the repository for existing screens, components, copy and
conventions, and reuse them before proposing new ones.

Write journeys (J1, ...) for the user's tasks; each lists its steps and the
acceptance criterion IDs it covers. Describe states (S1, ...) where they occur:
loading, empty, error, permission, success and partial results, with what the
user sees and can do next. Name the components to reuse or add, the exact copy
for labels, empty states and errors, keyboard and screen-reader use, and how the
layout works on a narrow screen. For each open interaction choice, record the
options, your choice and the reason in decisions.

Do not invent business rules, permissions or data the PRD does not define; put
them in open_questions. Resolve findings_to_resolve as in the PRD protocol: one
resolution per finding ID, fixed or rejected with a concrete reason; human
findings must be fixed.
