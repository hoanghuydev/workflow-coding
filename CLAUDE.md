@AGENTS.md

## Claude Code

- Run `start`, `approve`, `revise`, `retry`, `research` and `resume` with `--detach`
  and Bash `run_in_background: true`. You are notified when the command exits, so
  don't poll or sleep. Then read its output file and continue from the exit code.
- After a session restart, check running tasks with `status <id>`; if a supervisor is
  still running, run `wait <id>` with `run_in_background: true` instead of `resume`.
- If sandboxing blocks the spawned CLIs (network, or writes to `~/.codex`,
  `~/.claude`), ask the user before rerunning outside the sandbox.
- Ask for a gate decision in plain text. A permission prompt for an `approve`
  command is not a gate decision.
- Before changing a tracked file here, ask the direct-or-flow question from
  AGENTS.md "Changing this repo" in plain text. Approving an Edit or Write
  permission prompt is not that answer.
