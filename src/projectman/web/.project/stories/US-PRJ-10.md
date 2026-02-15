---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-10
points: 8
priority: must
status: done
tags: []
title: Detail views with inline editing
updated: '2026-02-15'
---

As a user, I want detail pages for epics, stories, and tasks so that I can view full information and edit fields inline.

**Epic detail (`/epics/{id}`):**
- Frontmatter fields (status, priority, target date, tags)
- Linked stories list with status/points
- Rollup stats (total/completed points, completion %)
- Inline edit: click field to toggle edit mode, save via PATCH

**Story detail (`/stories/{id}`):**
- Frontmatter fields (status, priority, points, epic link)
- Rendered markdown body
- Child tasks list with status/assignee
- Inline edit for frontmatter fields

**Task detail (`/tasks/{id}`):**
- Frontmatter fields (status, points, assignee)
- Parent story context (link + story title)
- Status transition buttons (todo → in-progress → review → done)
- Grab button (calls POST `/api/tasks/{id}/grab`)

**Acceptance criteria:**
- All three detail views render with full data
- Inline editing saves via HTMX PATCH without page reload
- Status transitions work via button clicks
- Markdown body rendered as HTML
- 404 page for invalid IDs