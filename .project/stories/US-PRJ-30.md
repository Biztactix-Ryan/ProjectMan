---
acceptance_criteria:
- load_config() uses module-level cache
- Cache has TTL or explicit invalidation on config write
- Repeated calls in same process return cached result
- _save_config() invalidates the cache
- All existing tests pass
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-30
points: 2
priority: must
status: backlog
tags:
- tier-1
- caching
- performance
title: Add config caching with TTL
updated: '2026-03-06'
---

As a developer, I want config.py to cache loaded config so that repeated tool calls don't re-read config.yaml from disk every time. Currently load_config() does a fresh file read on every call. In hub mode with 20+ subprojects, a single git_status_all() loads config ~20 times.