---
assignee: claude
created: '2026-03-05'
id: US-PRJ-27-9
points: 1
status: done
story_id: US-PRJ-27
title: 'Test: write_index reuses cached data'
updated: '2026-03-06'
---

Populate the cache via list calls, then call write_index. Mock frontmatter.load to assert it is NOT called again during indexing.