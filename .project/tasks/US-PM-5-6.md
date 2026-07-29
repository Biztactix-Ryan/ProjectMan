---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-5-5
id: US-PM-5-6
points: 1
status: done
story_id: US-PM-5
tags: []
title: Decide the removal policy for orphaned test tasks
updated: '2026-07-29'
---

When a criterion is deleted, its test task must not be silently destroyed if work has started against it. Proposed: delete when the task is untouched (todo, no assignee, no run-log entries), otherwise flag it for human attention.