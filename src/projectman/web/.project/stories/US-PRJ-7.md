---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-7
points: 3
priority: must
status: done
tags: []
title: Dashboard view
updated: '2026-02-15'
---

As a user, I want a dashboard at `/` showing project health at a glance so that I can quickly assess status.

**Displays:**
- Project name and description
- Completion percentage with visual progress bar
- Counts by status (stories: backlog/ready/active/done; tasks: todo/in-progress/review/done/blocked)
- Total vs completed story points
- Quick action links (view board, create story, run audit)

**Data sources:** `pm_status()` + `pm_active()`

**Acceptance criteria:**
- Dashboard loads at `/` route
- Shows real-time data from `.project/` files
- Quick links navigate to correct views
- Handles empty project state gracefully (no stories yet)