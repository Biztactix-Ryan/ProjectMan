---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-9
points: 1
status: done
story_id: US-PRJ-26
title: 'Test: Subsequent list calls return from cache not disk'
updated: '2026-03-05'
---

Call list_tasks() twice in succession, assert second call returns identical data without re-globbing. Use timing or mock to verify.