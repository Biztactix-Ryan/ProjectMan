---
acceptance_criteria:
- Two Store instances on the same project dir create stories in turn and both stories
  survive with distinct IDs
- Removing a task file and then creating a task yields an ID higher than every surviving
  task
- Every create path raises instead of overwriting when the target file already exists
- Item creates write atomically via _atomic_write_text
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-24
points: 3
priority: must
status: done
tags:
- store
- data-integrity
- subtraction
title: Store never silently overwrites an item on create
updated: '2026-09-05'
---

As a user with more than one Claude session open on the same project, I want story and task creation to be collision-safe so that a second session can never overwrite a story the first one just wrote.

Audit findings in src/projectman/store.py:
- `_next_story_id` (~line 553) is a per-process counter read from config.yaml at Store construction. Two live Stores hand out the same ID and `create_story` (~line 820) does a plain `write_text` with no exists check, so the second write silently replaces the first story.
- `_next_task_id` (~line 559) is `len(list_tasks(story_id)) + 1`. After any task file is removed (archive, manual delete, cleanup) the next create collides with a surviving higher-numbered task.
- Epic, sprint and changeset creates have the same plain `write_text` shape (~lines 1557, 2555). Only the run-log path uses `_atomic_write_text`.

Fix shape: allocate story IDs as max(config counter, highest existing ID on disk) + 1; allocate task IDs as highest existing numeric suffix + 1; every create refuses (raises) if the target path already exists; creates write through `_atomic_write_text` so a crash mid-write cannot leave a truncated file. `create_tasks` pre-computes a batch of IDs and must use the same rule.