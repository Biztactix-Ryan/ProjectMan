---
assignee: null
created: '2026-02-15'
id: US-PRJ-17-3
points: 2
status: done
story_id: US-PRJ-17
title: Add 'Add Task' dialog to story_detail.html
updated: '2026-02-15'
---

Add an 'Add Task' button in the Tasks section header of the story detail view. Opens a <dialog> with fields: title (required), description (required textarea), points (select: Fibonacci). story_id is auto-filled from the current story. On submit, POST to /api/tasks, show toast, refresh detail view.