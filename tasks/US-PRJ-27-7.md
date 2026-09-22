---
assignee: claude
created: '2026-03-05'
id: US-PRJ-27-7
points: 1
status: done
story_id: US-PRJ-27
title: 'Test: All mutation methods invalidate/update cache entries'
updated: '2026-03-06'
---

For each mutation (create_story, create_task, update, archive), call list_* before and after, verify the cache reflects the change without a full reload.