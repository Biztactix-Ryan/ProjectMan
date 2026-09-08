---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PRJ-39-4
id: US-PRJ-39-5
points: 1
status: done
story_id: US-PRJ-39
tags: []
title: Prove the index stays consistent and the existing cache tests still pass
updated: '2026-09-07'
---

Extend tests/test_web_store_caching.py (or a new tests/test_store_cache_index.py): after create, update, archive and invalidate, the index and the list agree (same IDs, same positions); a lookup by ID after 500 creates does not iterate (patch the list's __iter__ or assert the dict path is taken). Run tests/test_web_store_caching.py, tests/test_bulk_update.py and tests/test_bulk_archive.py.