---
assignee: claude
created: '2026-03-05'
id: US-PRJ-28-6
points: 2
status: done
story_id: US-PRJ-28
title: Add cache eviction policy for bounded memory
updated: '2026-03-06'
---

Ensure archived/done items don't bloat the cache indefinitely. Options: (a) exclude archived items from cache, (b) set a max cache size with LRU eviction, or (c) periodically clear cache on reindex. Pick the simplest approach — likely just filtering archived items out of cached lists since they're rarely queried.