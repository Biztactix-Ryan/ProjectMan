---
acceptance_criteria:
- Store holds parsed frontmatter in memory after first load
- Subsequent list_tasks/list_stories/list_epics calls return from cache not disk
- Cache is per-Store instance with a module-level shared cache dict
- Sub-second response for listing tasks of a story with 50+ tasks
created: '2026-03-05'
epic_id: EPIC-PRJ-5
id: US-PRJ-26
points: 8
priority: must
status: done
tags: []
title: In-Memory Cache Layer for Store
updated: '2026-03-05'
---

As a developer using PM tools, I want frontmatter data cached in memory so that repeated list/get calls don't re-read every file from disk each time.