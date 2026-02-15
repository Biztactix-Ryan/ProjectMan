---
assignee: null
created: '2026-02-15'
id: US-PRJ-17-1
points: 2
status: done
story_id: US-PRJ-17
title: Add 'New Epic' dialog to epics.html
updated: '2026-02-15'
---

Add a 'New Epic' button next to the page heading that opens a <dialog> modal with fields: title (required), description (required textarea), priority (select: must/should/could/wont), target date (date input), tags (comma-separated text). On submit, POST to /api/epics, show toast, refresh list, navigate to new epic.