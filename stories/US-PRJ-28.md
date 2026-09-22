---
acceptance_criteria:
- Server._store() returns a cached Store instance per project instead of creating
  a new one each call
- Cache persists across MCP tool invocations within the same server process
- Memory usage stays bounded — cache doesn't grow unbounded with archived items
- Tests verify cache hit behavior across multiple sequential tool calls
created: '2026-03-05'
epic_id: EPIC-PRJ-5
id: US-PRJ-28
points: 5
priority: must
status: done
tags: []
title: Server-Level Store Singleton and Cache Lifecycle
updated: '2026-03-06'
---

As a developer, I want the MCP server to reuse a single Store instance (or shared cache) across tool calls so that the cache actually persists between requests.