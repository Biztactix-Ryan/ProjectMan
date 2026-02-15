---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-12
points: 5
priority: should
status: done
tags: []
title: Audit and burndown views
updated: '2026-02-15'
---

As a user, I want read-only audit and burndown views so that I can monitor project health and velocity.

**Audit view (`/audit`):**
- Run audit on page load via GET `/api/audit`
- Findings grouped by severity (error, warning, info)
- Each finding shows: type, description, affected item ID (linked)
- Summary count at top

**Burndown view (`/burndown`):**
- Chart showing total points vs completed points
- Use Chart.js (loaded from CDN) or simple HTML/CSS bar chart
- Data from GET `/api/burndown`

**Data sources:** `pm_audit()`, `pm_burndown()`

**Acceptance criteria:**
- Audit displays all finding types from `audit.py`
- Findings link to affected items
- Burndown chart renders with current data
- Both views handle empty state (no stories/tasks)