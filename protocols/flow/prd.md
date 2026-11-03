# Write or revise the PRD

Return the PRD schema. Describe what must be true for users, not how to build it.
Write narrow, testable requirements with stable IDs (R1, R2, ...) and a priority.
Every must requirement needs at least one acceptance criterion (AC1, ...) in
Given/When/Then form that a test or a person can check without interpretation.
State non-goals explicitly so the scope stays as small as the request allows.
Read the repository only to understand current behaviour and vocabulary.
For a defect report, state the observed and the expected behaviour, and make the
reproduction an acceptance criterion that fails today.

Do not invent business rules, limits, fees or policies; put each unknown in
open_questions. Use research claims only with their stated status: verified,
disputed or inconclusive. Treat research as AI analysis of a supplied packet,
not as human-confirmed fact.

When findings_to_resolve is non-empty, revise the previous PRD and return exactly
one resolution per finding ID: fixed, or rejected with a concrete reason.
Findings from source human must be fixed unless impossible; explain why if so.
Keep IDs stable when their meaning is unchanged. Return an empty resolutions
array on a first draft.
