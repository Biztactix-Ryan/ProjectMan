---
assignee: null
created: '2026-02-15'
id: US-PRJ-17-2
points: 2
status: done
story_id: US-PRJ-17
title: Add 'New Story' dialog to stories.html
updated: '2026-02-15'
---

Add a 'New Story' button next to the page heading that opens a <dialog> modal with fields: title (required), description (required textarea), priority (select), points (select: Fibonacci 1/2/3/5/8/13), epic (select dropdown populated from GET /api/epics). On submit, POST to /api/stories, show toast, refresh list, navigate to new story.