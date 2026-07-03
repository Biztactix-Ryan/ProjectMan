---
created: '2026-03-05'
id: EPIC-PRJ-5
points: null
priority: must
status: done
tags:
- performance
- caching
target_date: null
title: Improve Frontmatter Caching and Performance
updated: '2026-03-06'
---

Returning the list of tasks for a story is taking several seconds. We need to improve performance through caching. Since MCP tools are the only way tasks/stories get updated, full reads to disk shouldn't be necessary each time. Key goals:

- Implement an in-memory cache layer for frontmatter/task data
- Invalidate cache only when MCP write operations occur (create, update, archive, etc.)
- Eliminate redundant disk reads on repeated list/get/board/status calls
- Ensure cache consistency — MCP tools are the single source of mutations
- Target sub-second response times for story task listings and board views