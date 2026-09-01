---
assignee: claude
created: '2026-03-06'
depends_on: []
id: US-PRJ-30-6
points: 1
status: done
story_id: US-PRJ-30
tags: []
title: Add module-level config cache to config.py
updated: '2026-08-22'
---

Add a module-level dict cache keyed by project root path in config.py. load_config() should check cache first, populate on miss. Include a clear_config_cache() function for explicit invalidation.

Sprint 6 planning notes (2026-08-22):
- The MCP server is a long-lived process and users hand-edit .project/config.yaml (e.g. to flip `tools:` flags from US-PM-15), so a pure in-process cache would serve stale config indefinitely. Record config.yaml's mtime alongside the cached ProjectConfig and re-read when it changes — this is the "TTL or explicit invalidation" the story asks for, with mtime standing in for a TTL.
- The acceptance criterion names `_save_config()`; the function in config.py is `save_config()`. Invalidate there (US-PRJ-30-7).
- Keep `load_config(root)` signature unchanged; tests in tests/test_config.py must still pass.