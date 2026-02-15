---
created: '2026-02-15'
epic_id: EPIC-PRJ-1
id: US-PRJ-2
points: 8
priority: must
status: done
tags: []
title: REST API endpoints
updated: '2026-02-15'
---

As a developer, I want REST API endpoints that wrap existing Store and business logic modules so that all ProjectMan operations are accessible over HTTP.

**Endpoints to implement in `routes/api.py`:**

Project:
- GET `/api/status` → `pm_status()`
- GET `/api/config` → `load_config()`

Epics:
- GET `/api/epics` → `store.list_epics()`
- POST `/api/epics` → `store.create_epic()`
- GET `/api/epics/{id}` → `pm_epic()` (with rollup)
- PATCH `/api/epics/{id}` → `store.update()`
- DELETE `/api/epics/{id}` → `store.archive()`

Stories:
- GET `/api/stories` → `store.list_stories(?status=)`
- POST `/api/stories` → `store.create_story()`
- GET `/api/stories/{id}` → `store.get_story()`
- PATCH `/api/stories/{id}` → `store.update()`
- DELETE `/api/stories/{id}` → `store.archive()`

Tasks:
- GET `/api/tasks` → `store.list_tasks(?story_id=&status=)`
- POST `/api/tasks` → `store.create_task()`
- GET `/api/tasks/{id}` → `store.get_task()`
- PATCH `/api/tasks/{id}` → `store.update()`
- POST `/api/tasks/{id}/grab` → `pm_grab()`
- DELETE `/api/tasks/{id}` → `store.archive()`

Board & Intelligence:
- GET `/api/board` → `pm_board()`
- GET `/api/burndown` → `pm_burndown()`
- GET `/api/audit` → `pm_audit()`
- GET `/api/search?q=` → `pm_search()`

Documentation:
- GET `/api/docs` → `pm_docs()` (summary)
- GET `/api/docs/{name}` → `pm_docs(doc=name)`
- PUT `/api/docs/{name}` → `pm_update_doc()`

All endpoints accept optional `?project=` query param for hub mode.

**Acceptance criteria:**
- All endpoints return proper JSON responses
- HTTP status codes follow REST conventions (201 for create, 404 for not found, etc.)
- OpenAPI docs at `/docs` show all endpoints with schemas