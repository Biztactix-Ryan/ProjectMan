---
assignee: claude
created: '2026-03-05'
id: US-PRJ-26-6
points: 2
status: done
story_id: US-PRJ-26
title: Add cache-aware get methods to Store
updated: '2026-03-05'
---

Modify `get_story()`, `get_task()`, `get_epic()` to look up individual items from the cache dict first. If the full list cache is populated, extract from there. If not, fall back to single-file read and optionally populate that entry. Body content (markdown below frontmatter) should also be cached since pm_board reads task bodies.