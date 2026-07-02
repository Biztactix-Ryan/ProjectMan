---
name: pm-do
description: Execute a single ProjectMan task end-to-end — claim it, load story context, implement, verify the DoD with evidence, record the outcome, and complete. Use when the user names a task to implement or says "do task X".
disable-model-invocation: true
args: "<task-id> [--complete]"
---

# /pm-do — Execute Task

## Flags

- `--complete` — Autonomous mode for spawned agents: no human is watching. Mark the task `done` only when every DoD item is verified with evidence; otherwise mark it `review` with a note. Then end the session without suggesting further actions.

## Phase 1: Claim & Context

1. Call `pm_get(task_id)` to read the task.
2. If the task is `todo` with no assignee: call `pm_grab(task_id)` to claim it (validates readiness including cross-story dependencies). If grab fails, log it — `pm_update(task_id, outcome="blocked", note="<blockers>")` — then stop and show the blockers.
3. If the task is `in-progress` with a different assignee: warn ("assigned to {assignee} — proceed anyway?") and only continue if explicitly confirmed. In `--complete` mode, stop instead: another agent may be working on it.
4. Read the parent story with `pm_get(story_id)` for acceptance criteria and context.
5. Review the task's Implementation section and DoD checklist. Check `pm_run_log` history on the task — a previous failed attempt tells you what to avoid.

## Phase 2: Execute

6. Read project documentation if touching unfamiliar areas: `pm_docs("project")`.
7. Implement the work described in the task — follow its implementation notes, write/modify the specified files.
8. **Verify with evidence, not assertion**: run the tests the task or story names (or the project's standard test command for the files you touched) and make them pass. For each DoD item, identify the concrete artifact that satisfies it — a file, a passing test, a command output.

## Phase 3: Record & Complete

9. Set the status and log the outcome in **one** `pm_update` call — `outcome` + `note` append a run-log entry alongside the status change:
   - All DoD items evidenced → `pm_update(task_id, status="done", outcome="success", note="<tests run + result, files changed>")`
   - Partially done / needs human judgment → `status="review"`, `outcome="partial"`, note what's unmet
   - Couldn't proceed → keep/restore an accurate status and log `outcome="blocked"` or `outcome="failed"` with why
10. **`--complete` mode rule**: `status="done"` only if step 8 produced evidence for every DoD item — anything less is `review`. Never mark done on unverified claims; the orchestrator independently validates and a false "done" becomes a failed retry.
11. Story rollup: if all sibling tasks are now `done` — in `--complete` mode set the story `done` automatically; interactively, suggest it.
12. Note downstream effects: tasks that were waiting on this one are now unblocked — name them.
13. Summarize: what was done, files changed, tests run and their results.
    - **`--complete` mode**: end the session here. Include status, files, and test evidence in your final report — it will be independently verified.
    - **Default**: suggest the next action ("Check the board: `/pm board`").

## Cross-Story Dependency Awareness

When a task has `depends_on` entries from other stories:
- Dependency status is shown in `pm_grab` and `pm_context` responses (id, title, status, type).
- If any dependency is not done, the task cannot be grabbed.
- Completing a task may unblock tasks in other stories — mention them in your summary.
