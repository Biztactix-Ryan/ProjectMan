---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-32-8
points: 2
status: todo
story_id: US-PRJ-32
tags: []
title: Pre-load all task bodies in pm_board instead of per-task get_task()
updated: '2026-03-06'
---

In server.py pm_board(), replace the per-task store.get_task(task.id) loop with a single pass that reads bodies from the cached list data. If list cache includes bodies, use them directly. Otherwise, batch-read all needed task files once.