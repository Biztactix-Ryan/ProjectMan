---
acceptance_criteria:
- All Store mutation methods (create_story/task/epic update archive) invalidate or
  update the relevant cache entries
- Cache invalidation is surgical — only affected entries are evicted not the whole
  cache
- write_index reuses cached data instead of re-reading from disk
- No stale data observed after any mutation sequence
created: '2026-03-05'
epic_id: EPIC-PRJ-5
id: US-PRJ-27
points: 5
priority: must
status: done
tags: []
title: Cache Invalidation on MCP Mutations
updated: '2026-03-06'
---

As a developer, I want the cache to stay consistent when tasks/stories are created, updated, archived, or grabbed, so that stale data is never returned.