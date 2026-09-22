---
assignee: claude
created: '2026-03-05'
id: US-PRJ-28-7
points: 1
status: done
story_id: US-PRJ-28
title: 'Test: Server._store() returns cached Store instance per project'
updated: '2026-03-06'
---

Call _store() twice with the same project name, assert the same object is returned (identity check with `is`). Call with different project, assert different instance.