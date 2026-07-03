---
acceptance_criteria:
- Secondary dict index maintained alongside cache list
- Cache update/invalidation is O(1) by ID
- Index stays consistent across append/update/invalidate operations
created: '2026-03-09'
epic_id: EPIC-PRJ-7
id: US-PRJ-39
points: 3
priority: should
status: backlog
tags:
- performance
- caching
title: Add secondary index for O(1) cache lookups by ID
updated: '2026-03-09'
---

As a developer, I want cache update/invalidation to be O(1) instead of O(n) so that mutations on large projects are fast. Currently _cache_update_entry (store.py line 324) does linear search through entire cache list to find one item. Add a dict-based secondary index keyed by item ID.