---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PRJ-39-4
points: 2
status: todo
story_id: US-PRJ-39
tags: []
title: Add a per-type dict index beside the cache list and use it in _cache_update_entry
updated: '2026-09-06'
---

In src/projectman/store.py the module-level _cache holds a list of (meta, body) per cache key and _cache_update_entry (around line 1702) walks the list to find one ID. Add a parallel `_cache_index[key][item_id] -> position` (or switch the cache value to an insertion-ordered dict keyed by ID, which is simpler and keeps iteration order) so update, evict-on-archive and single-item invalidation are O(1). Populate it wherever the list is filled (the miss path near line 1634) and clear it wherever the list is dropped (invalidation near line 1689). Keep get_cache_stats and the hit/miss/invalidation counters unchanged.