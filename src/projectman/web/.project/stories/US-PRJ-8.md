---
created: '2026-02-15'
epic_id: EPIC-PRJ-2
id: US-PRJ-8
points: 8
priority: must
status: done
tags: []
title: Board view with HTMX drag-drop
updated: '2026-02-15'
---

As a user, I want a kanban board at `/board` so that I can see task status and move tasks between columns.

**Columns:** Available | In Progress | Review | Blocked | Done

**Features:**
- Task cards showing title, points, assignee, parent story
- Readiness badges (ready/not-ready) from `check_readiness()`
- Drag-drop between columns via HTMX + Sortable.js to trigger status updates
- Dropping a card fires PATCH `/api/tasks/{id}` to update status
- Color coding by priority or status

**Data source:** `pm_board()`

**HTMX partials:**
- `_partials/task_card.html` — single task card (swappable)
- `_partials/status_badge.html` — status/readiness indicator

**Acceptance criteria:**
- Board shows all tasks grouped by status
- Drag-drop updates task status via API
- Readiness indicators visible on each card
- Board refreshes without full page reload (HTMX swap)