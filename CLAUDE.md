@AGENTS.md

## Claude Code

- Run `start`, `approve`, `revise`, `retry`, `research` and `resume` with Bash
  `run_in_background: true`. You are notified when the command exits, so don't poll
  or sleep. Then read its output file and continue from the exit code.
- If sandboxing blocks the spawned CLIs (network, or writes to `~/.codex`,
  `~/.claude`), ask the user before rerunning outside the sandbox.
- Ask for a gate decision in plain text. A permission prompt for an `approve`
  command is not a gate decision.
