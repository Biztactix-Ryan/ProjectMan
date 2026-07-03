---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-32-9
points: 2
status: todo
story_id: US-PRJ-32
tags: []
title: Refactor check_readiness to accept pre-loaded context
updated: '2026-03-06'
---

Modify check_readiness() in readiness.py to optionally accept pre-loaded story metadata and sibling task lists, avoiding per-task store.get_story() and store.list_tasks() calls. Keep backward-compatible signature with optional params.