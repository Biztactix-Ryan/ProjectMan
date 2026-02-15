---
assignee: claude
created: '2026-02-15'
id: US-PRJ-2-2
points: 3
status: done
story_id: US-PRJ-2
title: Implement epics and stories CRUD endpoints
updated: '2026-02-15'
---

Implement full CRUD endpoints for epics and stories, following the dependency pattern from task US-PRJ-2-1.

**Epic endpoints (5):**
- GET `/api/epics` → `store.list_epics()` — list all epics
- POST `/api/epics` → `store.create_epic(title, description, priority, target_date, tags)` — returns 201
- GET `/api/epics/{id}` → `pm_epic(id)` — includes story rollup (linked stories, points, completion %)
- PATCH `/api/epics/{id}` → `store.update(id, **fields)` — partial update (status, title, priority, etc.)
- DELETE `/api/epics/{id}` → `store.archive(id)` — soft delete via archive

**Story endpoints (5):**
- GET `/api/stories` → `store.list_stories(status=)` — list with optional `?status=` filter
- POST `/api/stories` → `store.create_story(title, description, priority, points, epic_id)` — returns 201
- GET `/api/stories/{id}` → `store.get_story(id)` — returns frontmatter + body
- PATCH `/api/stories/{id}` → `store.update(id, **fields)` — partial update
- DELETE `/api/stories/{id}` → `store.archive(id)` — soft delete

**HTTP conventions:**
- POST returns 201 Created with the created resource
- GET returns 200 with resource(s)
- PATCH returns 200 with updated resource
- DELETE returns 200 with confirmation
- 404 for unknown IDs (catch FileNotFoundError or similar from Store)

**Files to modify:**
- `web/routes/api.py`

**Acceptance criteria:**
- All 10 endpoints work and return proper JSON
- Correct HTTP status codes
- Filtering works (stories by status)
- Epic detail includes rollup data
- 404 returned for invalid IDs
- All visible in OpenAPI docs at `/docs`