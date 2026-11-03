# AGENTS.md

> If this lab launched you as a worker (your input is a job packet with a
> `FLOW_STAGE` header, or a research packet), ignore this file and follow the packet.

This repo is a work-flow orchestrator. `run_flow.py` drives Codex, Claude Code and
Antigravity through triage → PRD → techspec → code → supervisor-run tests →
cross-review, and stops at gates where a human decides. `run_lab.py` is a standalone
research pipeline. Human docs: `README.md`, `docs/flow.md`, `docs/research.md`.

In this repo you usually do one of two jobs:

1. **Operate the flow for the user** (default). Turn what they want into a task, run
   it, read what comes back, and bring each decision to them in plain words.
2. **Change the lab itself**, only when they ask for it. See "Developing the lab".

Reply in the user's language (usually Vietnamese). Commands below run from the repo
root with `.venv/bin/python`.

## Rules for operating

- **Gates belong to the user.** Run `approve`, `revise`, `reject`, `retry` or
  `research` only after the user has read your summary of *that* gate and told you
  what to do. One decision covers one gate. If they ask you to approve future gates
  in advance, explain that each gate is where a person checks what the AI produced,
  and keep asking at each one.
- Never use `--auto-approve` except with `--demo`.
- Never merge, push, rebase or delete the `flow/<id>` branch, and never edit files
  under `tasks/<id>/`. Merging is the user's job.
- Report only what you read. Say "the reviewer says X", not "X". Give file paths so
  the user can check.
- Every command except `status`, `list` and `graph` can spend model quota. Tell the
  user before starting a task.

## Starting a task

1. Find out, asking only for what you cannot look up:
   - **What to build**, in the user's words.
   - **Target repo** (`--repo`) and **base branch** (`--base`, usually `main`).
   - **Test command** (`--test`). Look in the target repo (Makefile, package.json,
     go.mod, CI config) and propose one. Tests run by the supervisor are the only test
     evidence the flow trusts. Without `--test` the release gate shows tests as not run.
   - **Risk floor** (`--risk`). Propose one; triage can raise it but never lower it.
     P0: money, idempotency, authorization, merchant isolation. P1: deploy, migration,
     integrations (the default). P2: lists, filters, dashboards. P3: demos and
     experiments. Higher tiers add documents, gates and reviewers.
   - **Sources** (`--brief`), only if the work depends on outside facts the repo lacks.
   - **Skills** (`--skill`, repeatable). Read the `SKILL.md` descriptions in the target
     repo's `.agents/skills/` and `.claude/skills/` and in this repo's `.agents/skills/`.
     Pick only the skills that fit this request, since each one adds tokens to every
     code-stage call. Tell the user which you picked and why.
2. Write the request to `requests/<yyyymmdd>-<slug>.md` (this folder is gitignored).
   Write it like a ticket for a developer: goal, context, the constraints the user
   stated, and what is out of scope. Don't invent requirements. Put your guesses under
   an "Open questions" heading so the PRD step and the gates bring them up. Show the
   request to the user and get a go-ahead.
3. Start the task:

   ```bash
   .venv/bin/python run_flow.py start --request requests/<file>.md \
     --repo <path> --base main --test "<command>" --risk P2
   ```

   The first line of stdout is the task directory. Its basename is the task id.

### Rules and skills

`start` prints the `rules:`, `task skills:` and `skill scripts` it sealed into the task.
Tell the user which ones apply. If they mention conventions that no rule covers,
suggest adding them before starting. See README "Rule và skill" for where each kind
lives. Rules are binding; skills are guidance and rank below rules. Project rules and
skills are read from the base commit, so they must be committed first. Workers never
see the user's `~/.claude` or `~/.codex` files.

## Long-running commands

`start`, `approve`, `revise`, `retry`, `research` and `resume` call models. Each one
can take from a few minutes to over an hour, since every CLI job may run up to
`--timeout` seconds (default 900).

- **How to run them.** Run in the background, or with a timeout of at least two
  hours, and wait for the command to exit. Don't poll in a loop.
- **Don't interfere.** Don't kill a running command, and don't start a second command
  on the same task (a lock refuses it).
- **If interrupted.** If your session ended or the process died, run `status <id>`
  and then `resume <id>`. Finished model calls are reused, not paid twice.
- **Sandbox access.** These commands spawn `codex`, `claude` and `agy`, which need
  network access and write access to their home directories. If your sandbox blocks
  that, ask the user for permission instead of retrying.

| Exit | Meaning | What you do |
| --- | --- | --- |
| 0 | approved at the release gate | report the result (see "When it finishes") |
| 2 | waiting at a gate | summarize the gate and ask the user |
| 1 | rejected, or an error (`Flow error: ...` on stderr) | explain it |
| 130 | interrupted | `status <id>`, then `resume <id>` |

At a gate, stdout ends with `awaiting human (<kind>): <gate file>` and
`actions: <allowed commands>`.

## Summarizing a gate

Read the gate file first; it links the rest. Then read what the gate is about:

| Gate | Also read |
| --- | --- |
| `research` | triage's open questions, in the gate file |
| `prd` | `tasks/<id>/docs/prd.md` |
| `techspec` | `tasks/<id>/docs/techspec.md`, plus `prd.md` if the user has not seen it |
| `release` | the newest `tasks/<id>/tests/round-N.log` (its tail), and the diff: `git -C tasks/<id>/worktree diff <base_sha> HEAD` (`base_sha` is in `tasks/<id>/task.json`) |
| `blocked` | `manifest.json` and `stderr.log` of the failed job under `tasks/<id>/jobs/` |

Then tell the user, briefly:

- the stage, the risk tier, and model calls used against the limit (`status <id>`);
- what the AI produced, in a few lines;
- each open blocker or major finding in one line, with who raised it;
- at the release gate: the test result, the files changed, and anything reviewers
  marked `not_met` or `unverified`;
- what deserves a close look, and your own recommendation, labelled as yours;
- the actions this gate accepts.

## Turning the user's answer into a command

| The user wants | Command |
| --- | --- |
| to go ahead | `approve <id>`, with `--note "..."` for any guidance and `--risk Px` if they change the tier |
| changes | `revise <id> --note "..."`: keep their wording and add section or file references. The next round must resolve the note as a blocker |
| to stop | `reject <id> --note "<reason>"` |
| to supply sources (research gate) | write a brief (format: `inputs/brief.md`), then `research <id> --brief <file>`. To skip research: `approve <id>` |
| to retry after a block | explain the cause first, then `retry <id>`; add `--max-calls N` if the call limit was hit |

If you fetch sources for a brief, put the URL and retrieval time in each `Source`
section and tell the user which sources you chose. Then run the command as described
under "Long-running commands" and continue from its exit code.

## When it finishes

On exit 0, read `tasks/<id>/report.md` and tell the user:

- the branch `flow/<id>` in the target repo, and its commits;
- the test result;
- the document paths;
- the model calls used.

Then give them the commands to review and merge it themselves:

- to see the change: `git -C <repo> diff <base>...flow/<id>`
- after merging: `git -C <repo> worktree remove <tasks/<id>/worktree path>`

Don't run the merge.

## Coming back later

`run_flow.py list` shows every task with its risk and what it is waiting for.
`run_flow.py status <id>` shows one task. Start there when the user returns to
earlier work.

## Research only

For a question instead of a code change:

1. Write a brief whose `Source S01`, `S02`... sections contain the source text itself
   (template: `inputs/brief.md`).
2. Run `.venv/bin/python run_lab.py --brief <path>`. This makes 13 model calls, and
   the path is relative to the repo root.
3. Read `runs/<run-id>/final-report.md`.
4. Summarize the verified, disputed and inconclusive findings separately. "Verified"
   means an AI checked the claim against the given sources, not that a person did.
   The pipeline does not browse, so don't run it without sources.

## Trying it out

`run_flow.py start --demo --auto-approve` runs the whole flow offline with fake CLIs
and a throwaway repo, at no cost. Use it to show a new user how the flow works.

## Developing the lab

- Run `.venv/bin/python -m unittest discover -s tests` before claiming a change works.
  The tests are offline and use `tests/fake_cli.py`. Never call real CLIs from tests.
- Keep the invariants listed in `docs/flow.md` ("Bất biến"). In particular:
  - Paid calls go through `JobRunner`, with job ids derived from state.
  - Code decides routing; model verdicts do not.
  - Nothing merges or pushes.
- Prompts, protocols and personas are written in English. README and `docs/` are in
  Vietnamese.
- Don't commit `config/agents.local.json`, `tasks/`, `runs/` or `requests/`.
