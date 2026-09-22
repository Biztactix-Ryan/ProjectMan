---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on: []
id: US-PM-24-6
points: 1
status: done
story_id: US-PM-24
tags: []
title: Task ID allocation uses the highest existing suffix plus one
updated: '2026-09-05'
---

Replace `_next_task_id` (store.py ~line 559): parse the numeric suffix of every existing task file for the story (including archived ones if archive keeps the ID namespace — check store.archive) and return `<story>-<max+1>`. `create_tasks` (~line 1753) pre-computes a batch from `_next_task_id` and increments — keep that but seed it from the new rule. Unit test: create three tasks, delete the middle file, create another, assert its ID is -4.