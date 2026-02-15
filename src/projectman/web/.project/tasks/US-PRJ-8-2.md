---
assignee: null
created: '2026-02-15'
id: US-PRJ-8-2
points: 2
status: done
story_id: US-PRJ-8
title: Build task card and status badge HTMX partials
updated: '2026-02-15'
---

Create HTMX partial templates:
- `templates/_partials/task_card.html` — displays task title, points, assignee, parent story link; swappable via HTMX
- `templates/_partials/status_badge.html` — status/readiness indicator with appropriate styling
- Each card links to task detail view
- Cards render within board columns