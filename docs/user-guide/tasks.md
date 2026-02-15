# Tasks

## Format

Tasks are markdown files in `.project/tasks/` with YAML frontmatter:

```yaml
---
id: APP-1-1
story_id: APP-1
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

## Work Order Concept

Each task is a self-contained work order with:
- **Implementation** — what to build
- **Testing** — how to verify
- **Definition of Done** — completion criteria
