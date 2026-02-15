---
assignee: null
created: '2026-02-15'
id: US-PRJ-10-2
points: 2
status: done
story_id: US-PRJ-10
title: Create story detail view with rendered markdown body and child tasks
updated: '2026-02-15'
---

Create `templates/story_detail.html` extending base.html:
- Page route at `/stories/{id}` in `routes/pages.py`
- Display frontmatter: status, priority, points, epic link
- Render markdown body as HTML (use `markdown` library or Jinja2 filter)
- Child tasks list with status/assignee badges
- 404 page for invalid story IDs