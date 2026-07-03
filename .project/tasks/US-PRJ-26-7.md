---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-7
points: 1
status: done
story_id: US-PRJ-26
title: Add cache stats and clear_cache() utility
updated: '2026-03-05'
---

Add a `clear_cache()` method on Store and a module-level `clear_all_caches()`. Add basic stats (hits, misses, invalidations) accessible via a debug flag. This supports testing and debugging cache behavior.