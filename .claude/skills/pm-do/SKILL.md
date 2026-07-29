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

1. Call `pm_grab(task_id)` to claim the task. Its response already contains the task body, the parent story context (acceptance criteria), open sibling tasks, and dependency status — do **not** also call `pm_get` on the task or story.
   - If grab fails, log it — `pm_update(task_id, outcome="blocked", note="<blockers>")` — then stop and show the blockers.
   - If grab reports the task is already assigned to someone else: warn ("assigned to {assignee} — proceed anyway?") and only continue if explicitly confirmed (then `pm_get(task_id)` to read it without re-claiming). In `--complete` mode, stop instead: another agent may be working on it.
2. Review the task's Implementation section and DoD checklist. Check `pm_run_log` history on the task — a previous failed attempt tells you what to avoid.

## Phase 2: Execute

3. Read project documentation if touching unfamiliar areas: `pm_docs("project")`.
4. Implement the work described in the task — follow its implementation notes, write/modify the specified files.
5. **Verify with evidence, not assertion**: run the tests the task or story names (or the project's standard test command for the files you touched) and make them pass. For each DoD item, identify the concrete artifact that satisfies it — a file, a passing test, a command output.

## Phase 3: Record & Complete

6. Record the outcome in **one** call:
   - All DoD items evidenced, continuing to another task → `pm_done_next(task_id, outcome="success", note="<tests run + result, files changed>")` — completes the task, appends the run log, auto-closes the story if this was its last open task, and returns the next ready task already claimed.
   - All DoD items evidenced, stopping here (e.g. `--complete` mode) → `pm_update(task_id, status="done", outcome="success", note="...")`
   - Partially done / needs human judgment → `pm_update(task_id, status="review", outcome="partial", note="<what's unmet>")`
   - Couldn't proceed → keep/restore an accurate status and log `outcome="blocked"` or `outcome="failed"` with why
7. **`--complete` mode rule**: `status="done"` only if step 5 produced evidence for every DoD item — anything less is `review`. Never mark done on unverified claims; the orchestrator independently validates and a false "done" becomes a failed retry.
8. Story rollup: `pm_done_next` closes the story automatically when its last task completes. If you used `pm_update` instead and all sibling tasks are now `done` — in `--complete` mode set the story `done`; interactively, suggest it.
9. Note downstream effects: tasks that were waiting on this one are now unblocked — name them.
10. Summarize: what was done, files changed, tests run and their results.
    - **`--complete` mode**: end the session here. Include status, files, and test evidence in your final report — it will be independently verified.
    - **Default**: if `pm_done_next` returned a next task, offer to continue with it; otherwise suggest the board (`/pm board`).

## Cross-Story Dependency Awareness

When a task has `depends_on` entries from other stories:
- Dependency status is shown in `pm_grab` and `pm_context` responses (id, title, status, type).
- If any dependency is not done, the task cannot be grabbed.
- Completing a task may unblock tasks in other stories — mention them in your summary.
