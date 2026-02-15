---
created: '2026-02-15'
epic_id: EPIC-PRJ-4
id: US-PRJ-17
points: 8
priority: must
status: done
tags: []
title: Add creation forms for Epics, Stories, and Tasks in the web UI
updated: '2026-02-15'
---

As a project manager, I want to create new Epics, Stories, and Tasks directly from the web dashboard so that I don't need to use the CLI for basic item creation.

Acceptance criteria:
- "New Epic" button on Epics list page opens a dialog with title, description, priority, target date, and tags fields
- "New Story" button on Stories list page opens a dialog with title, description, priority, points, and epic link fields
- "Add Task" button on Story detail page opens a dialog with title, description, and points fields
- "Add Story" button on Epic detail page opens a dialog pre-filled with the epic linkage
- All forms validate required fields and show success/error toasts
- After creation, the list/detail view refreshes and navigates to the new item