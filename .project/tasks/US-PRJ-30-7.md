---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-30-7
points: 1
status: todo
story_id: US-PRJ-30
tags: []
title: Invalidate config cache on _save_config()
updated: '2026-03-06'
---

In store.py _save_config(), call config.clear_config_cache() (or invalidate the specific root key) after writing config.yaml to disk. Ensures cache stays consistent after mutations like next_id increments.