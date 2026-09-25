# AI Collaboration Blackboard

This folder is the shared workspace for Codex and Claude Code. Use it when both assistants are open on ClearDrive and need to coordinate without forking project reality.

## Files

- `current-state.md` — concise snapshot of what is true right now.
- `task-board.md` — active work, owner, status, and next action.
- `codex-to-claude.md` — Codex handoffs, questions, and review requests for Claude.
- `claude-to-codex.md` — Claude handoffs, questions, and review requests for Codex.
- `session-log.md` — append-only record of notable actions, findings, and handoffs.

## Protocol

1. Read `current-state.md`, `task-board.md`, and your inbound handoff file before starting coordinated work.
2. Own one active implementation task at a time. Do not let both assistants edit the same code path simultaneously.
3. Use handoff files for questions and review requests. Keep them short, dated, and actionable.
4. Update `task-board.md` when starting, blocking, handing off, or finishing a task.
5. Append important facts to `session-log.md`; do not rewrite history.
6. Record settled decisions in `notes/decisions.md`, not only in this folder.

## Status Markers

- `todo` — not started.
- `in-progress` — actively owned by one assistant.
- `blocked` — needs Austin or external state.
- `review` — ready for the other assistant to inspect.
- `done` — finished and verified.

