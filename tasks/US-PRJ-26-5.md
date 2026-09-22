---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-5
points: 3
status: done
story_id: US-PRJ-26
title: Add module-level cache dict and cache-aware list methods to Store
updated: '2026-03-05'
---

Add a module-level `_cache` dict keyed by (base_dir, item_type). Modify `list_stories()`, `list_tasks()`, `list_epics()` to check the cache before globbing disk. On cache miss, populate from disk. Return copies to prevent mutation. The cache stores parsed frontmatter objects (not raw file content) so Pydantic validation only runs once.