---
assignee: null
created: '2026-03-06'
depends_on:
- US-PRJ-32-8
- US-PRJ-32-9
id: US-PRJ-32-10
points: 1
status: todo
story_id: US-PRJ-32
tags: []
title: Wire pre-loaded context through pm_board readiness loop
updated: '2026-03-06'
---

In pm_board(), build story_cache and siblings_cache maps before the task loop. Pass these into check_readiness() to eliminate N+1 I/O. Should reduce 300 file ops to ~3 for a 100-task board.