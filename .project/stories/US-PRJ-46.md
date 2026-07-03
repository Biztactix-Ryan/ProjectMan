---
acceptance_criteria:
- _next_task_id uses directory glob count instead of list_tasks
- Batch create_tasks generates IDs without N list_tasks calls
- Existing tests still pass
created: '2026-03-09'
epic_id: EPIC-PRJ-8
id: US-PRJ-46
points: 2
priority: could
status: backlog
tags:
- batch
- performance
title: Optimize _next_task_id to avoid full task list load
updated: '2026-03-09'
---

As a developer, I want task ID generation to be fast so that batch task creation scales. Currently store.py _next_task_id (lines 89-92) calls list_tasks(story_id) just to count tasks. For batch creation via create_tasks, this is called once per task. Should use glob count on tasks_dir instead.