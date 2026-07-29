---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-16-5
points: 2
status: done
story_id: US-PM-16
tags: []
title: Add an archived state for tasks
updated: '2026-07-29'
---

Either add archived to TaskStatus or introduce an archived boolean orthogonal to status. The boolean is likely cleaner — it preserves the task's last real status, which matters for the migration and for understanding why work was abandoned.

Fix the dispatch at store.py:1082-1088 so tasks no longer route to done.