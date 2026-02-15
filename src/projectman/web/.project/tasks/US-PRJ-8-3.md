---
assignee: null
created: '2026-02-15'
id: US-PRJ-8-3
points: 3
status: done
story_id: US-PRJ-8
title: Add Sortable.js drag-drop with HTMX status updates
updated: '2026-02-15'
---

Add interactive drag-drop to board:
- Include Sortable.js (CDN) for drag-drop between columns
- On drop, fire PATCH `/api/tasks/{id}` to update task status based on target column
- HTMX swap to update the card in place after status change
- Visual feedback during drag (opacity, shadow)
- Board refreshes without full page reload