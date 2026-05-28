---
name: pm-orchestrate
description: Drive the active sprint to done by dispatching /pm-do worker subagents sequentially. Reads the sprint plan, picks the next ready task, spawns an isolated agent to implement it, then loops until the sprint is complete or blocked.
user_invocable: true
disable-model-invocation: true
args: "[--sprint <id>] [--max <n>] [--dry-run] [--auto]"
---

# /pm-orchestrate — Sprint Orchestrator

You are the **orchestrator**, not a worker. You read the sprint, pick the next ready task, hand it off to a `/pm-do --complete` subagent, then evaluate and pick the next. You do **not** implement tasks yourself.

## Flags

- `--sprint <id>` — Drive a specific sprint instead of the active one
- `--max <n>` — Stop after `n` tasks have been dispatched (safety budget; default no limit)
- `--dry-run` — Show the execution plan and stop. Do not spawn any workers.
- `--auto` — Skip the pre-flight "ready to start?" confirmation. Still confirms on errors and at the end.

## Operating Model

- **Concurrency**: sequential. One worker at a time. The next worker is not spawned until the previous one finishes.
- **Commits**: stage-only. Workers leave changes staged (or unstaged) in the working tree. The orchestrator does **not** commit code, does **not** call `pm_commit`, and does **not** push. The user reviews everything at the end.
- **`.project/` state**: workers update task status via MCP tools, which write to `.project/` files. Leave those uncommitted too — the user decides what to commit.

## Phase 1 — Pre-flight

1. Resolve target sprint:
   - If `--sprint <id>` was given, call `pm_get_sprint(id)`.
   - Otherwise call `pm_list_sprints(status="active")`. If none → stop with "No active sprint. Run `/pm-plan` first." If multiple → list them and ask which.
2. Call `pm_status` and `pm_audit`.
   - If `pm_audit` returns ERROR-level findings (e.g. dependency cycles, done-story-with-incomplete-tasks), **stop** and show them. Ask the user to fix or pass `--auto` is not enough — these need human attention.
3. Call `pm_board` and `pm_active`.
   - If any of the sprint's tasks are `in-progress` and assigned to someone other than the orchestrator's spawned agents, warn and ask before proceeding.
4. Run `git status --short` to record the starting working-tree state. Save the list of pre-existing modified files so the final summary can distinguish orchestrator-caused changes.

## Phase 2 — Build the Execution Plan

5. For each story in the sprint:
   - Call `pm_get(story_id)` to list its tasks.
   - For each task: capture `id`, `title`, `status`, `assignee`, `depends_on`, `points`.
6. Filter to tasks that still need work: status in `{todo, in-progress, review, blocked}`. Skip `done`.
7. Topologically order them by `depends_on` (intra-story and cross-story). Tasks blocked by incomplete cross-story dependencies that are **not** in the sprint should be flagged — they'll never become ready under this run.
8. Present the plan as a numbered list:
   ```
   Sprint: <name> (<id>)
   Plan: N tasks across M stories

   1. US-PRJ-1-1  Add schema           [todo, 2pts, ready]
   2. US-PRJ-1-2  Test: schema         [todo, 1pt, blocked by US-PRJ-1-1]
   3. US-PRJ-2-1  Frontend integration [todo, 3pts, blocked by US-PRJ-1-3 (not in sprint!)]
   ...
   ```
9. **If `--dry-run`** → stop here.
10. **Unless `--auto`** → ask: "Start orchestration? [y/N]". Stop on anything but yes.

## Phase 3 — Execution Loop

Repeat until the loop exits:

11. Refresh state: call `pm_board` (cheap) to get the current ready pool.
12. Pick the next task to dispatch:
    - From the sprint plan, the first task whose status is `todo`, has no assignee, and whose `depends_on` are all `done`.
    - If none are ready but some are `in-progress` or `review` from a previous orchestrator run → stop and report; the human needs to resolve those.
    - If none remain unfinished → loop exits successfully.
13. Check the `--max` budget. If exceeded → stop and report.
14. **Spawn the worker** via the `Agent` tool:
    - `subagent_type`: `general-purpose`
    - `description`: `pm-do <task-id>` (short)
    - `prompt`: a self-contained brief (see "Worker Prompt" below)
    - Run in the **foreground** (you need the result before picking the next task)
    - Do **not** use `isolation: "worktree"` — we're sequential and stage-only, so isolation just adds merge overhead
15. After the worker returns:
    - Call `pm_get(task_id)` to verify final status.
    - **Pass**: status is `done`. Append to "completed" list, continue.
    - **Review**: status is `review`. Append to "needs review" list, continue (do not block — humans review at the end).
    - **Fail**: status is still `todo`, `in-progress`, or `blocked`, OR the worker reported an error. Stop the loop, record what happened, surface the failure.
16. Quick health check every 3 tasks: re-run `pm_audit` with a brief summary. If new ERROR-level findings appeared, stop.

## Phase 4 — Final Report

When the loop exits (success, budget hit, or failure):

17. Show a summary:
    - Sprint progress: tasks done before vs. after, points moved
    - Tasks completed by this run (IDs + titles)
    - Tasks left in `review` needing human attention
    - Tasks left untouched and why (blocked, budget, error)
    - Stories now fully done (suggest moving to `done` status)
18. Run `git status --short` and `git diff --stat` (compared to the pre-flight snapshot). Show:
    - Code files changed by orchestrated work
    - `.project/` files changed (status updates)
19. Suggest next actions — do NOT execute them yourself:
    - "Review the diff: `git diff`"
    - "Commit code when ready: standard git workflow"
    - "Commit project state: `/pm commit all`"
    - "Re-run to continue: `/pm-orchestrate`"
    - If sprint is fully done: "Mark sprint complete: `/pm update <sprint-id> status=done`"

## Worker Prompt Template

When spawning each worker via the `Agent` tool, send a self-contained prompt. The subagent has no prior context.

```
You are executing a single ProjectMan task. The orchestrator has already
verified that this task is ready (dependencies done, status todo).

Task: <task-id>
Title: <task-title>
Parent story: <story-id> — <story-title>
Sprint: <sprint-id>

Run the /pm-do skill with arguments: `<task-id> --complete`

The --complete flag means: implement the task, verify all DoD criteria,
call pm_update to mark it done (or review if criteria are not fully met),
then end your session without suggesting further actions.

IMPORTANT — staging-only mode:
- DO NOT run `git commit`, `git push`, `pm_commit`, or `pm_push`.
- Leave all code changes in the working tree (staged or unstaged is fine).
- Status updates via pm_update are expected; they write to .project/ files
  which is fine, just don't commit them.
- The human will review and commit everything at the end.

Report back: final task status, files you changed, and any blockers you
encountered. Keep your reply under 200 words.
```

## Stop Conditions (Summary)

The loop stops when **any** of the following holds:
- All sprint tasks are `done`
- `--max` budget reached
- A worker leaves its task in a non-`done`, non-`review` state
- `pm_audit` produces a new ERROR-level finding mid-run
- The next ready task can't be found because everything is blocked by out-of-sprint dependencies
- Worker reports an unrecoverable blocker

In every case, run Phase 4 before exiting.

## What This Skill Does NOT Do

- **No parallel workers.** Sequential by design.
- **No worktrees / no branch management.** Workers share the same working tree.
- **No commits, no pushes.** Stage-only.
- **No scoping or planning.** If the sprint has undecomposed stories or unestimated tasks, stop and direct the user to `/pm-plan` or `/pm-autoscope`.
- **No implementation by the orchestrator.** Always delegate to a `/pm-do --complete` subagent — even for trivial tasks. This keeps the orchestrator's context clean.
