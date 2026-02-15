---
assignee: null
created: '2026-02-15'
id: US-PRJ-7-1
points: 2
status: done
story_id: US-PRJ-7
title: Create dashboard template with status summary and progress bar
updated: '2026-02-15'
---

Create `templates/dashboard.html` extending base.html:
- Page route at `/` in `routes/pages.py`
- Display project name and description from config
- Completion percentage with visual progress bar (CSS width based on %)
- Total vs completed story points
- Data sourced from `pm_status()` and `pm_active()`
- Handle empty project state gracefully (no stories yet)