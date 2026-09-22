---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-10
points: 1
status: done
story_id: US-PRJ-26
title: 'Test: Cache is per-Store instance with module-level shared dict'
updated: '2026-03-05'
---

Create two Store instances pointing to the same base_dir, verify they share the same cache. Create one with a different base_dir, verify isolation.