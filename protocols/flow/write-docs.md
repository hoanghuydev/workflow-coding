# Write or update documentation in the worktree

You work in a git worktree on a dedicated branch. Write the documentation the
request asks for, in the files and format the repository already uses. Every
claim about behaviour, parameters, defaults, errors and limits must match the
code or a source named in the request; read the code to confirm it. If they
conflict, document the code's behaviour and record the conflict in open_questions.

Give examples the reader can copy and run. Mark any example you could not
verify. Follow the binding rules and any format skill supplied. Do not change
code, tests, CI or configuration unless the request asks for it.

The supervisor commits your work and runs the test command, if any, itself.
List every changed file in changes; tests may be empty. When findings_to_resolve
is non-empty, return exactly one resolution per finding ID: fixed, rejected with
concrete evidence, or deferred (minor only). Human findings must be fixed.
Fill brief in everyday words: what readers will notice, 3-5 steps a person can
follow to check it, and what is still missing or unverified.
