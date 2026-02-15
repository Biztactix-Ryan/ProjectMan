---
assignee: null
created: '2026-02-15'
id: US-PRJ-17-4
points: 2
status: done
story_id: US-PRJ-17
title: Add 'Add Story' dialog to epic_detail.html
updated: '2026-02-15'
---

Add an 'Add Story' button in the Stories section of the epic detail view. Opens the same story creation dialog but with epic_id pre-filled from the current epic. On submit, POST to /api/stories with epic_id set, show toast, refresh detail view.