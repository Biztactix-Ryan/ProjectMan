---
name: pm-do
description: Execute a task — grab if needed, load context, implement, and complete
user_invocable: true
disable-model-invocation: true
args: "<task-id> [--complete]"
---

# /pm-do — Execute Task

## Flags

- `--complete` — Auto-close mode: skip the review option, mark the task as `done` when all DoD criteria are met, and end the session. Designed for spawned agents that should finish without manual intervention.

## Phase 1: Claim & Context

1. Call `pm_get(task_id)` to read the task
2. If the task is `todo` with no assignee:
   - Call `pm_grab(task_id)` to claim it (validates readiness including cross-story dependencies)
   - If grab fails, stop and show the blockers
3. If the task is `in-progress` with a different assignee:
   - Warn: "This task is assigned to {assignee}. Proceed anyway?"
   - Only continue if explicitly confirmed
4. Read the parent story for broader context:
   - Call `pm_get(story_id)` to understand acceptance criteria
5. **Check cross-story dependencies**: If the task depends on tasks from other stories, verify those are done
6. Review the task's Implementation section and DoD

## Phase 2: Execute

7. Read project documentation if touching new areas:
   - Call `pm_docs("project")` for architecture context
8. Implement the work described in the task:
   - Follow the implementation instructions
   - Write/modify the specified files
   - Run tests as described
9. Verify ALL DoD criteria are met — check off each item

## Phase 3: Complete

10. **If `--complete` flag is set:**
   - Call `pm_update(task_id, status="done")` — do NOT offer a review option
   - Check if all sibling tasks in the story are done:
     - If all done, call `pm_update(story_id, status="done")` automatically
   - Summarize what was done, files changed, tests run
   - **End the session.** Do not suggest further actions.

   **Otherwise (default):**
   - Call `pm_update(task_id, status="review")` if the task needs human review,
     OR call `pm_update(task_id, status="done")` if all DoD criteria are met
11. Check if all sibling tasks in the story are done:
    - Call `pm_active` or list tasks for the story
    - If all done, suggest: "All tasks for {story_id} are complete — update story to done?"
12. **Check downstream dependencies**: After completing, notify about tasks that were waiting on this one
    - "Task US-PRJ-2-1 is now unblocked and ready to work"
13. Summarize what was done, files changed, tests run
14. Suggest next action: "Check the board for more work: `/pm board`"

## Cross-Story Dependency Awareness

When a task has `depends_on` entries from other stories:
- The dependency status is shown in `pm_grab` and `pm_context` responses
- Each dependency shows: id, title, status, and type (task/story)
- If any dependency is not done, the task cannot be grabbed
- After completing a task, downstream tasks in other stories may become unblocked
