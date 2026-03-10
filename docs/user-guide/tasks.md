# Tasks

## Format

Tasks are markdown files in `.project/tasks/` with YAML frontmatter:

```yaml
---
id: US-APP-1-1
story_id: US-APP-1
title: "Implement login endpoint"
status: todo
points: 3
assignee: claude
tags: [backend, auth]
depends_on: [US-APP-1-2]
created: 2026-01-15
updated: 2026-01-15
---

## Implementation

Add POST /api/login endpoint that validates credentials and returns JWT.

## Testing

- Unit test for credential validation
- Integration test for the full login flow

## Definition of Done

- [ ] Endpoint implemented
- [ ] Tests pass
- [ ] Error handling for invalid credentials
```

## Lifecycle

`todo` → `in-progress` → `review` → `done`

Tasks can also be `blocked` if waiting on dependencies.

## Task Board & Readiness

Tasks appear on the task board (`/pm board`) when they pass readiness checks enforced by the Definition of Ready.

**Hard gates** (must all pass for a task to be available):
- Status is `todo`
- No assignee (not already claimed)
- Has a point estimate
- Description is at least 50 characters
- Parent story is in `active` or `ready` status
- All `depends_on` tasks are `done`

**Suitability hints** (informational signals, not blockers):
- `well-scoped` — task is clearly defined
- `has-impl-plan` — has an Implementation section
- `has-test-plan` — has a Testing section
- `has-dod` — has a Definition of Done checklist
- `quick-win` — low-effort task suitable for quick progress

Use `/pm-do US-APP-1-1` to grab and execute a task directly from the board.

## Work Order Concept

Each task is a self-contained work order with:
- **Implementation** — what to build
- **Testing** — how to verify
- **Definition of Done** — completion criteria

Tasks must meet the readiness hard gates above before they can be picked up from the board. Well-formed work orders that include all three sections will score higher on suitability hints.

## Dependencies

Tasks can declare dependencies on sibling tasks (tasks under the same story) using the `depends_on` field:

```yaml
depends_on: [US-APP-1-2, US-APP-1-3]
```

**Rules:**
- Dependencies must be siblings (same `story_id`)
- Self-references are rejected
- Circular dependencies are detected and rejected (cycle detection uses DFS)
- The task board uses topological sorting to order tasks by dependency chain

**Readiness impact:** A task with incomplete dependencies will not appear as "available" on the board. It moves to the `not_ready` group until all `depends_on` tasks reach `done` status.

## Run Log

Tasks (and stories/epics) maintain a run log that tracks work attempts. Each entry records what happened and whether it succeeded, partially worked, or failed.

Log entries are created by passing `outcome` and `note` to `pm_update`:

```
pm_update("US-APP-1-1", status="in-progress", outcome="partial", note="Built endpoint, auth tests failing")
pm_update("US-APP-1-1", outcome="blocked", note="Need DB migration from US-APP-1-2 first")
pm_update("US-APP-1-1", status="done", outcome="success", note="All tests green")
```

**Outcome values:** `success`, `partial`, `blocked`, `failed`, `info`

**Reading the log:** Use `pm_run_log("US-APP-1-1")` to see all entries (most recent first). `pm_get` also shows the 3 most recent entries.

**Storage:** `.project/logs/{item_id}.jsonl` — one JSONL file per item, append-only.

## Tags

Tasks support free-form tags for categorization and filtering:

```yaml
tags: [backend, auth, quick-win]
```

Tags are filterable in `pm_board`, `pm_active`, and `pm_search` via the `tag` parameter.
