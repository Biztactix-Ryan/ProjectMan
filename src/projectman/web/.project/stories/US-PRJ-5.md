---
created: '2026-02-15'
epic_id: EPIC-PRJ-1
id: US-PRJ-5
points: 5
priority: must
status: done
tags: []
title: API test suite
updated: '2026-02-15'
---

As a developer, I want FastAPI TestClient tests so that API endpoints are verified and regressions are caught.

**Test coverage:**
- Status and config endpoints return valid JSON
- CRUD lifecycle for epics, stories, and tasks (create → read → update → archive)
- Filtering: stories by status, tasks by story_id
- Board, burndown, audit, search endpoints
- Documentation read/write endpoints
- Error cases: 404 for missing items, 422 for invalid input
- Hub mode: `?project=` parameter forwarding

**Setup:**
- Use FastAPI `TestClient` (from `starlette.testclient`)
- Create temporary `.project/` directory per test (reuse pattern from existing `conftest.py`)

**Acceptance criteria:**
- All API endpoints have at least one happy-path test
- Error cases tested (not found, invalid input)
- Tests pass in CI alongside existing test suite