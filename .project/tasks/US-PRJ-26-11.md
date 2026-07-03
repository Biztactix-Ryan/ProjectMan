---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-11
points: 1
status: done
story_id: US-PRJ-26
title: 'Test: Sub-second response for listing tasks of a story with 50+ tasks'
updated: '2026-03-05'
---

Create 50+ task files, time a list_tasks(story_id=X) call. First call populates cache, second call must complete in under 100ms.