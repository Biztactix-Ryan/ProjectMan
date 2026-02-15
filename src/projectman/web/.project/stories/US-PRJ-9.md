---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-9
points: 5
priority: must
status: done
tags: []
title: Epic and story list views
updated: '2026-02-15'
---

As a user, I want list pages for epics and stories so that I can browse and filter project items.

**Epics list (`/epics`):**
- Table with columns: ID, title, status, priority, story count, progress bar
- Status badges (draft/active/done)
- Click row to navigate to detail view

**Stories list (`/stories`):**
- Filterable table: filter by status, priority, epic
- Sortable columns: title, priority, points, status, updated date
- Status and priority badges
- Click row to navigate to detail view

**Acceptance criteria:**
- Both lists render from API data
- Filters update list via HTMX (no full reload)
- Sortable columns work
- Empty states handled (no epics/stories yet)