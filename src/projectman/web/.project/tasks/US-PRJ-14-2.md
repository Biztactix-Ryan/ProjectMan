---
assignee: null
created: '2026-02-15'
id: US-PRJ-14-2
points: 3
status: done
story_id: US-PRJ-14
title: Create hub dashboard with per-project cards and aggregate rollup
updated: '2026-02-15'
---

Create `templates/hub.html` extending base.html:
- Page route at `/hub` in `routes/pages.py`
- Project cards showing per-project: name, status, completion %, point totals
- Aggregate rollup section: total points across all projects, overall completion
- Links from each card to per-project dashboard (with `?project=` param)
- Data from `hub.rollup.rollup()` and `pm_context()`