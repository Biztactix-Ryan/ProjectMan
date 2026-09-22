---
assignee: claude
created: '2026-03-05'
id: US-PRJ-27-6
points: 1
status: done
story_id: US-PRJ-27
title: Make write_index and build_index use cached data
updated: '2026-03-06'
---

Modify `build_index()` in indexer.py to accept optional pre-loaded lists or to call Store methods that hit the cache. Currently `build_index(store)` calls `store.list_stories()`, `store.list_tasks()`, `store.list_epics()` — these should now hit cache automatically, but verify the flow and ensure no redundant disk reads remain.