---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-33-5
points: 2
status: todo
story_id: US-PRJ-33
tags: []
title: Refactor pm_epic to load all tasks once then filter by story_id
updated: '2026-03-06'
---

In server.py pm_epic(), replace the per-story list_tasks(story_id=sid) calls with a single store.list_tasks() call, then filter in memory using a dict keyed by story_id. This reduces N glob+parse operations to 1.