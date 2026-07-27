---
name: brief-executor
description: Execute a ClearDrive execution brief. Use when the user pastes a brief, says "start brief N", asks to implement a numbered spec, or when work begins on a branch like brief-3-capture. Covers anchor verification, plan restatement, acceptance runs, PR body format, and the decisions.md entry.
---

# Executing a ClearDrive brief

Briefs are specifications, not suggestions. The system depends on implementing what was
specified or reporting why it can't — never quietly substituting a different design.

## Before editing
1. Read the brief fully.
2. Verify every line anchor by grepping the quoted string. Line numbers drift.
3. If any precondition fails — file missing, signature differs, string absent — stop and
   report, quoting the actual code. Do not proceed with an approximation.
4. Restate the plan in <=10 lines. Wait for confirmation on decision-bearing briefs
   (schemas, model SKU, protocol work).

## Branch and scope
One brief, one branch (brief-<N>-<slug>), one PR. Diffs stay inside the brief's declared
file list. Note necessary out-of-scope fixes in the PR body; do not fold them in.

## While implementing
- Path-scoped rules in .claude/rules/ load automatically. Read them — they encode failure
  modes that already happened once.
- Where the brief specifies exact text (prompt rules, forbidden byte lists), reproduce it
  exactly. Paraphrasing a safety rule is a defect.

## Acceptance
Run every acceptance command. Paste raw output, not a summary. If a criterion fails, say so
plainly with the failing output.

## Decisions log
Append to notes/decisions.md. Never edit or delete a prior entry; supersede it:

## [DECIDED] <title> — <date>
Context: <what forced the decision>
Decision: <what was chosen>
Evidence: <measured numbers, paths, or acceptance output>
Supersedes: <prior entry, if any>

Use [OPEN] for deferred decisions, naming the blocking condition.

## Hard stops
Stop and ask if: the brief conflicts with .claude/rules/, a change would send new bytes to a
vehicle, a schema change would invalidate existing corpus examples, or a quick fix would
touch ml/ scoring code mid-brief.
