---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-30-6
points: 1
status: todo
story_id: US-PRJ-30
tags: []
title: Add module-level config cache to config.py
updated: '2026-03-06'
---

Add a module-level dict cache keyed by project root path in config.py. load_config() should check cache first, populate on miss. Include a clear_config_cache() function for explicit invalidation.