---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-36-7
points: 1
status: todo
story_id: US-PRJ-36
tags: []
title: Document single-threaded cache assumption in store.py
updated: '2026-03-06'
---

Add docstring/comment at store.py module level (near line 20) stating the cache is not thread-safe and assumes single-threaded execution (MCP stdio transport). Note that Web UI async is safe but true threading would need locks.