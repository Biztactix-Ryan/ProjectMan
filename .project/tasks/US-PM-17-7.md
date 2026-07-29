---
assignee: null
created: '2026-07-30'
depends_on:
- US-PM-17-6
id: US-PM-17-7
points: 2
status: todo
story_id: US-PM-17
tags: []
title: Implement the chosen detection change in migrations.py
updated: '2026-07-30'
---

Apply the decision from the previous task to find_archived_as_done / migrate_archived_as_done. A task completed by a single todo-to-done write must not be a candidate, and no code path may move a task out of done without the agreed positive signal. Keep the existing skip-rather-than-write bias for every ambiguous case and preserve idempotency.