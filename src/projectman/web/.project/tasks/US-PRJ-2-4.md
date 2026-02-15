---
assignee: claude
created: '2026-02-15'
id: US-PRJ-2-4
points: 2
status: done
story_id: US-PRJ-2
title: Implement board, intelligence, and documentation endpoints
updated: '2026-02-15'
---

Implement the read-only intelligence endpoints and documentation CRUD.

**Board & Intelligence endpoints (4):**
- GET `/api/board` → `pm_board()` — task board grouped by status columns (available, in-progress, review, blocked, done) with readiness indicators
- GET `/api/burndown` → `pm_burndown()` — total vs completed points
- GET `/api/audit` → `pm_audit()` — run audit, return findings grouped by severity
- GET `/api/search?q=` → `pm_search(query)` — keyword/semantic search, returns matched items with snippets

**Documentation endpoints (3):**
- GET `/api/docs` → `pm_docs()` — summary of all docs with staleness indicators (file, last_modified, age_days, status)
- GET `/api/docs/{name}` → `pm_docs(doc=name)` — full content of a specific doc (project, infrastructure, security, vision, architecture, decisions)
- PUT `/api/docs/{name}` → `pm_update_doc(doc, content)` — replace doc content; request body is the new markdown content

**Files to modify:**
- `web/routes/api.py`

**Acceptance criteria:**
- Board returns tasks grouped by status with readiness info
- Burndown returns point totals
- Audit returns findings (or empty list for clean project)
- Search returns results with snippets for matching query
- Docs list shows all 6 doc types with staleness
- Doc detail returns full markdown content
- Doc update persists changes to `.project/` files
- All visible in OpenAPI docs