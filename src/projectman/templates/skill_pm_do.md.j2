---
name: pm-do
description: Execute a single ProjectMan task end-to-end — claim it, load story context, implement, verify the DoD with evidence, record the outcome, complete. Use when the user names a task or says "do task X".
disable-model-invocation: true
args: "<task-id> [--complete]"
---

# /pm-do — Execute Task

## Flags

- `--complete` — Autonomous mode for spawned agents: no human is watching. Mark the task `done` only when every DoD item is verified with evidence; otherwise `review` with a note. Then end the session without suggesting next actions.
  - **Not for `/pm-orchestrate` workers.** Dispatched *without* `--complete`: the worker leaves the task `in-progress` and `pm_accept` records the verdict and closes the task and its story. A worker-set `done` makes `pm_accept` answer `already_done` and the evidence never lands.

## Worker rules (orchestrated runs)

Your cwd may be a git worktree on branch `orch/<run>/<task-id>`. Never `git checkout`, `restore`, `stash`, `reset` or `clean`; never switch branches. Commit only when the dispatch prompt says so, and only code paths — never `.project`. The store is reached through the `pm_*` tools, never a `.project` directory.

## Phase 1: Claim & Context

1. Call `pm_grab(task_id)` to claim the task. Its response already carries the task body, parent story context (acceptance criteria), open sibling tasks and dependency status — do **not** also call `pm_get`.
   - If grab fails, log it — `pm_update(task_id, outcome="blocked", note="<blockers>")` — then stop and show the blockers.
   - If grab reports it assigned to someone else: warn ("assigned to {assignee} — proceed anyway?") and continue only if confirmed (then `pm_get(task_id)` to read it without re-claiming). In `--complete` mode, stop instead: another agent may be on it.
2. Review the task's Implementation section and DoD checklist. Check `pm_run_log` history — a previous failed attempt tells you what to avoid.

## Phase 2: Execute

3. Read project documentation if touching unfamiliar areas: `pm_docs("project")`.
4. Implement the work the task describes — follow its notes, write/modify the named files.
5. **Verify with evidence, not assertion**: run the tests the task or story names (or the project's standard command for the files you touched) and make them pass. For each DoD item name the artifact that satisfies it — a file, a passing test, a command output.

## Phase 3: Record & Complete

6. Record the outcome in **one** call:
   - All DoD items evidenced, continuing to another task → `pm_done_next(task_id, outcome="success", note="<tests run + result, files changed>")` — completes the task, appends the run log, closes the story if this was its last open task, and returns the next ready task, claimed.
   - All DoD items evidenced, stopping here (e.g. `--complete`) → `pm_update(task_id, status="done", outcome="success", note="...")`
   - Partially done / needs human judgment → `pm_update(task_id, status="review", outcome="partial", note="<what's unmet>")`
   - Couldn't proceed → keep an accurate status and log `outcome="blocked"` or `"failed"` with why
7. **`--complete` rule**: `status="done"` only if step 5 produced evidence for every DoD item — anything less is `review`. Never mark done on unverified claims; the orchestrator validates independently and a false "done" becomes a failed retry.
8. Story rollup: `pm_done_next` (and `pm_accept`, which shares its body) closes the story when this was its last open task. `pm_update(status="done")` does **not** — if you used it and all siblings are now `done`, in `--complete` mode set the story `done` yourself; interactively, suggest it.
9. Note downstream effects: tasks waiting on this one are now unblocked — name them.
10. Report back under 1500 chars, no code or logs, in this order: files changed (paths only); tests as `command -> pass|fail (n passed)`; DoD met; DoD unmet; blockers.
    - **`--complete`**: end here, same shape plus the status — it is independently verified.
    - **Default**: if `pm_done_next` returned a next task, offer to continue; else suggest `/pm board`.

## Cross-Story Dependency Awareness

For `depends_on` entries from other stories:
- Dependency status is shown in `pm_grab` and `pm_context` responses (id, title, status, type).
- A task whose dependency is not done cannot be grabbed.
- Completing one may unblock tasks in other stories — name them in your summary.
