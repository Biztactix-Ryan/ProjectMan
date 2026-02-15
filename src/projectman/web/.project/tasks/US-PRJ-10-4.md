---
assignee: null
created: '2026-02-15'
id: US-PRJ-10-4
points: 2
status: done
story_id: US-PRJ-10
title: Add HTMX inline editing for frontmatter fields on all detail views
updated: '2026-02-15'
---

Add inline editing to epic, story, and task detail views:
- Click on a frontmatter field to toggle edit mode (display → input field)
- Save via HTMX PATCH to the appropriate API endpoint
- Cancel to revert to display mode
- Fields to support: status (dropdown), priority (dropdown), points (number), title (text), assignee (text), target_date (date)
- Success feedback on save (field briefly highlights or shows check)