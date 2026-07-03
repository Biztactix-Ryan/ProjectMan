---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-30-8
points: 1
status: todo
story_id: US-PRJ-30
tags: []
title: Add tests for config cache hit and invalidation
updated: '2026-03-06'
---

Test that: (1) repeated load_config() calls return same object without re-reading file, (2) _save_config() invalidation causes next load to re-read, (3) different project roots have independent cache entries.