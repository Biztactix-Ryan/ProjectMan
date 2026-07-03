---
assignee: claude
created: '2026-03-05'
id: US-PRJ-27-5
points: 3
status: done
story_id: US-PRJ-27
title: Add cache invalidation to all Store write methods
updated: '2026-03-06'
---

After `create_story()`, `create_task()`, `create_epic()`, `create_tasks()`, `update()`, and `archive()` succeed, surgically update or evict the affected cache entry. For creates, append to the cached list. For updates, replace the entry in-place. For archive, update status in cache. Do NOT clear the entire cache — only touch the affected item.