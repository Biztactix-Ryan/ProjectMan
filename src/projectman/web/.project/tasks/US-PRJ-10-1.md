---
assignee: null
created: '2026-02-15'
id: US-PRJ-10-1
points: 2
status: done
story_id: US-PRJ-10
title: Create epic detail view with linked stories and rollup stats
updated: '2026-02-15'
---

Create `templates/epic_detail.html` extending base.html:
- Page route at `/epics/{id}` in `routes/pages.py`
- Display frontmatter: status, priority, target date, tags
- Linked stories list with status badges and points
- Rollup stats: total/completed points, completion %
- 404 page for invalid epic IDs
- Data from `pm_epic()` which includes rollup