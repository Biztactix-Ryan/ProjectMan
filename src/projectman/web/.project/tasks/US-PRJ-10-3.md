---
assignee: null
created: '2026-02-15'
id: US-PRJ-10-3
points: 2
status: done
story_id: US-PRJ-10
title: Create task detail view with status transitions and grab button
updated: '2026-02-15'
---

Create `templates/task_detail.html` extending base.html:
- Page route at `/tasks/{id}` in `routes/pages.py`
- Display frontmatter: status, points, assignee
- Parent story context (link + story title)
- Status transition buttons (todo → in-progress → review → done) — each fires PATCH via HTMX
- Grab button (calls POST `/api/tasks/{id}/grab`)
- 404 page for invalid task IDs