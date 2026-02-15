---
assignee: null
created: '2026-02-15'
id: US-PRJ-8-1
points: 2
status: done
story_id: US-PRJ-8
title: Create board page route and static kanban column layout
updated: '2026-02-15'
---

Create `templates/board.html` extending base.html:
- Page route at `/board` in `routes/pages.py`
- Five kanban columns: Available | In Progress | Review | Blocked | Done
- Column headers with task counts
- Data sourced from `pm_board()` API
- Static rendering first (no drag-drop yet)