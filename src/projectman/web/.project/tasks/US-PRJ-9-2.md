---
assignee: null
created: '2026-02-15'
id: US-PRJ-9-2
points: 3
status: done
story_id: US-PRJ-9
title: Create stories list template with HTMX filtering and sortable columns
updated: '2026-02-15'
---

Create `templates/stories.html` extending base.html:
- Page route at `/stories` in `routes/pages.py`
- Table with columns: ID, title, priority (badge), points, status (badge), epic, updated date
- Filter controls: filter by status, priority, epic — update list via HTMX (no full reload)
- Sortable column headers (click to sort by that column)
- Click row to navigate to `/stories/{id}` detail view
- Empty state handled