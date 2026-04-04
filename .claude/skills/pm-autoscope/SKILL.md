---
name: pm-autoscope
description: Automated scoping — discover and create epics, stories, and tasks in bulk
user_invocable: true
---

# /pm-autoscope — Automated Scoping

Automates the discovery and creation pipeline for epics, stories, and tasks.

## How it works

1. Call `pm_auto_scope()` to detect the project state and get discovery signals.
2. Based on the mode returned, follow the appropriate workflow below.

## Full Scan Mode (new projects)

Triggered when no epics or stories exist yet. The tool returns codebase signals (docs, build files, source tree).

**Workflow:**
1. Analyze the codebase signals returned by `pm_auto_scope`
2. Propose 2-5 epics covering the major areas of work
3. Present the epic list to the user for approval — let them add/remove/edit
4. Create approved epics with `pm_create_epic`
5. For each epic, propose 2-6 stories
6. Present stories to the user for approval per epic
7. Create approved stories with `pm_create_story`, linking to the epic via `epic_id`
   - **Set story dependencies**: If a story depends on another story being done first, use `depends_on`
8. For each story, propose 2-6 tasks
9. Present tasks to the user for quick approval
10. Create approved tasks with `pm_create_task`
11. Show summary: N epics, N stories, N tasks created, total points

## Incremental Mode (existing stories need tasks)

Triggered when stories exist but some have no tasks. This is the primary use case.

**Workflow:**
1. `pm_auto_scope` returns the list of undecomposed stories with their bodies
2. **Loop through each story**:
   a. Call `pm_scope(story_id)` to get full decomposition context
   b. Propose 2-6 tasks for the story based on its content
   c. Present the task list to the user for quick approval (yes/edit/skip)
   d. Create approved tasks with `pm_create_task`
3. After all stories are scoped, show summary:
   - N stories scoped
   - N tasks created
   - Total points assigned
4. Suggest next steps: `/pm board` to see available work or `/pm-plan` for sprint planning

## Guidelines

- Keep task titles as verb phrases: "Add authentication middleware", "Write unit tests for parser"
- Each task should be 1-5 points (completable in one session)
- Tasks should be independently testable
- First task in a story sets up the foundation
- Last task handles integration/cleanup
- Don't over-decompose — 2-6 tasks per story is the sweet spot

## Dependencies: `depends_on`

### Intra-Story Dependencies (within a story)
- **Create implementation tasks BEFORE test tasks** — implementation tasks get lower IDs
- **Test tasks MUST set `depends_on`** pointing to the implementation task(s) they verify
- This ensures the board shows implementation tasks first, and `pm_grab` picks them in the right order
- Example: if task -1 is "Add schema" and task -2 is "Test: schema", then -2 must have `depends_on: ["US-PRJ-X-1"]`

### Cross-Story Dependencies (between stories)
- **Tasks can depend on tasks from other stories**: Use when work in one story requires something from another
- **Stories can depend on other stories**: Use when a story can't start until another is complete
- Example: `US-PRJ-2-1` (frontend integration) depends on `US-PRJ-1-3` (API endpoint) from a different story

### Cross-Story Patterns
When scoping related stories, identify cross-story dependencies:
- **API-first**: Backend story tasks should be done before frontend integration tasks
- **Shared infrastructure**: Common utilities story should complete before dependent feature stories
- **Data flow**: Data model tasks should precede tasks that consume that data

### Batch Creation with Dependencies
Use `pm_create_tasks` (batch) to create all tasks at once:
- List implementation tasks first in the array
- List test tasks last with `depends_on` set
- For cross-story deps, reference existing task IDs from other stories

## Forcing a mode

Users can force a specific mode:
- `/pm autoscope full` — force full codebase scan even if stories exist
- `/pm autoscope incremental` — force incremental even if no stories exist
