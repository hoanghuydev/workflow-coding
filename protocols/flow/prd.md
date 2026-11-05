# Write or revise the PRD

Return the PRD schema. Describe what must be true for users, not how to build it.
Write narrow, testable requirements with stable IDs (R1, R2, ...) and a priority.
Every must requirement needs at least one acceptance criterion (AC1, ...) in
Given/When/Then form that a test or a person can check without interpretation.
Keep the three parts apart: `given` is the starting state, `when` is only the
action, and `then` is the expected outcome. Never write the outcome into `when`,
and never leave `then` empty.
State non-goals explicitly so the scope stays as small as the request allows.
Read the repository only to understand current behaviour and vocabulary.
For a defect report, state the observed and the expected behaviour, and make the
reproduction an acceptance criterion that fails today.

Fill brief for people who will not read the rest: what users will notice, the
main flow in 3-6 steps, what is left out and what could still go wrong, in
everyday words without IDs, code names or jargon. Record under assumptions each
choice you settled yourself from the request, the rules or the code, or as a
sensible reversible default, with the reason. Follow the recorded project
decisions in the Rules section unless the request changes them.

Do not invent business rules, limits, fees or policies; put each business policy
the request leaves open in open_questions with the options you see and the one
you would choose. A reviewer escalates the ones that matter to a person instead
of you guessing. Never turn a requirement the request already implies into a
question. Use research claims only with their stated status: verified,
disputed or inconclusive. Treat research as AI analysis of a supplied packet,
not as human-confirmed fact.

When findings_to_resolve is non-empty, revise the previous PRD and return exactly
one resolution per finding ID: fixed, or rejected with a concrete reason.
Findings from source human must be fixed unless impossible; explain why if so.
Keep IDs stable when their meaning is unchanged. Return an empty resolutions
array on a first draft.
