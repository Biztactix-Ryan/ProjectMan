---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-34-6
id: US-PM-34-7
points: 3
status: todo
story_id: US-PM-34
tags: []
title: Route every ID-taking tool through the resolver and remove its project parameter
updated: '2026-09-06'
---

For each of the 44 tools with project: Optional[str] = None: those that take an id, task_id, story_id, epic_id or sprint_id drop the parameter and call _store_for_id; multi-ID tools (pm_get, pm_batch_get, pm_update_many, pm_archive_many) use _stores_for_ids and merge results in input order; pm_create_task and pm_create_tasks resolve through story_id; pm_accept, pm_retry, pm_park, pm_review, pm_done_next, pm_grab and pm_release resolve through their task id and take the next task from the same store. Remove every 'project' line from the docstrings. Files: src/projectman/server.py plus the tests that pass project=.