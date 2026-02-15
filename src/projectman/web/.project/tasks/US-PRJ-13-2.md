---
assignee: null
created: '2026-02-15'
id: US-PRJ-13-2
points: 2
status: done
story_id: US-PRJ-13
title: Create search results page with grouped results and highlighting
updated: '2026-02-15'
---

Create `templates/search.html` extending base.html:
- Page route at `/search` in `routes/pages.py`
- Receives `?q=` query parameter
- Calls `pm_search()` with query
- Results grouped by type (epics, stories, tasks)
- Each result shows: title, type badge, status badge, snippet with keyword highlighting
- Click result navigates to detail view
- Handle empty query (show helpful message) and no results state