---
assignee: null
created: '2026-02-15'
id: US-PRJ-9-1
points: 2
status: done
story_id: US-PRJ-9
title: Create epics list template with status badges and progress bars
updated: '2026-02-15'
---

Create `templates/epics.html` extending base.html:
- Page route at `/epics` in `routes/pages.py`
- Table with columns: ID, title, status (badge), priority, story count, progress bar (completion %)
- Status badges styled by state (draft/active/done)
- Click row to navigate to `/epics/{id}` detail view
- Empty state handled (no epics yet)