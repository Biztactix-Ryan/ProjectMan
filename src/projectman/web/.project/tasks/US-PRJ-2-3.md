---
assignee: claude
created: '2026-02-15'
id: US-PRJ-2-3
points: 2
status: done
story_id: US-PRJ-2
title: Implement tasks CRUD and grab endpoint
updated: '2026-02-15'
---

Implement full CRUD endpoints for tasks plus the special grab (claim) endpoint.

**Task endpoints (6):**
- GET `/api/tasks` → `store.list_tasks(story_id=, status=)` — list with optional `?story_id=` and `?status=` filters
- POST `/api/tasks` → `store.create_task(story_id, title, description, points)` — returns 201
- GET `/api/tasks/{id}` → `store.get_task(id)` — returns frontmatter + body
- PATCH `/api/tasks/{id}` → `store.update(id, **fields)` — partial update (status, points, assignee, title)
- POST `/api/tasks/{id}/grab` → `pm_grab(task_id, assignee)` — claim task with readiness validation; accepts optional `assignee` in request body (defaults to "claude")
- DELETE `/api/tasks/{id}` → `store.archive(id)` — soft delete

**Grab endpoint specifics:**
- Validates task readiness before claiming (uses `check_readiness()`)
- Sets status to in-progress and assigns
- Returns the claimed task with context (parent story info)
- Returns 409 Conflict or 422 if task not ready (with readiness failure reasons)

**Files to modify:**
- `web/routes/api.py`

**Acceptance criteria:**
- All 6 endpoints work and return proper JSON
- Task filtering by story_id and status works
- Grab validates readiness and returns clear errors if not ready
- Correct HTTP status codes (201, 200, 404, 409/422)
- All visible in OpenAPI docs