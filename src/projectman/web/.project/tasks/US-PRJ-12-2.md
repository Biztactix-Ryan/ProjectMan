---
assignee: null
created: '2026-02-15'
id: US-PRJ-12-2
points: 3
status: done
story_id: US-PRJ-12
title: Create burndown chart view with Chart.js
updated: '2026-02-15'
---

Create `templates/burndown.html` extending base.html:
- Page route at `/burndown` in `routes/pages.py`
- Include Chart.js from CDN
- Render chart showing total points vs completed points from GET `/api/burndown`
- Simple bar or line chart
- Handle empty state (no stories/tasks = show message instead of empty chart)
- Data injected into template as JSON for Chart.js initialization