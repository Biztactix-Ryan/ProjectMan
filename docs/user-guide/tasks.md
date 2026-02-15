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
