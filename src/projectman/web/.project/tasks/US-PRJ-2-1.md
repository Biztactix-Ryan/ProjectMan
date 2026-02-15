---
assignee: claude
created: '2026-02-15'
id: US-PRJ-2-1
points: 1
status: done
story_id: US-PRJ-2
title: Implement project/config endpoints and hub mode dependency pattern
updated: '2026-02-15'
---

Implement the foundational API endpoints and establish the dependency injection pattern used by all subsequent tasks.

**Endpoints:**
- GET `/api/status` → calls `pm_status()` from `server.py` (or equivalent Store/indexer logic)
- GET `/api/config` → calls `load_config()` from `config.py`

**Hub mode pattern:**
- All endpoints accept optional `?project=` query parameter
- Create a FastAPI dependency (e.g. `get_root(project: Optional[str] = None)`) that resolves the project root, handling hub mode when `project` is provided
- Create a `get_store(root=Depends(get_root))` dependency for Store access
- This pattern will be reused by all CRUD tasks

**Files to modify:**
- `web/routes/api.py` — add endpoints and dependencies
- `web/app.py` — ensure router is included (should already be from US-PRJ-1)

**Acceptance criteria:**
- GET `/api/status` returns JSON with project name, epic/story/task counts, points, completion %
- GET `/api/config` returns project config as JSON
- `?project=` parameter accepted (no-op for non-hub projects)
- Dependency injection pattern documented with docstrings for reuse