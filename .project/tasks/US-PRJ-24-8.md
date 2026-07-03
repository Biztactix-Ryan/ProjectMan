---
assignee: claude
created: '2026-02-23'
id: US-PRJ-24-8
points: 1
status: done
story_id: US-PRJ-24
title: Add depends_on to web API schemas and routes
updated: '2026-03-01'
---

Update web schemas and routes to support depends_on.

## Implementation
- Edit `src/projectman/web/schemas.py`:
  - CreateTaskRequest: add `depends_on: Optional[list[str]] = None`
  - UpdateItemRequest: add `depends_on: Optional[list[str]] = None`
  - TaskResponse: add `depends_on: list[str] = []`
- Edit `src/projectman/web/routes/api.py` create_task(): pass `depends_on=body.depends_on`

## Testing
- Verify web API accepts and returns depends_on

## Definition of Done
- [ ] All three schemas updated
- [ ] Route passes depends_on through
- [ ] Tests pass