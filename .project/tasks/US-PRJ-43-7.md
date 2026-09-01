---
assignee: claude
created: '2026-08-22'
depends_on: []
id: US-PRJ-43-7
points: 1
status: done
story_id: US-PRJ-43
tags: []
title: Partition one list_tasks call by story_id in pm_epic
updated: '2026-08-22'
---

src/projectman/server.py pm_epic calls store.list_tasks(story_id=story.id) once per linked story. Replace with a single store.list_tasks() followed by an in-memory partition into {story_id: [tasks]} and look each story up in that dict. Rollup arithmetic (archived tasks excluded from both numerator and denominator), pagination and the per-story task_summary must be unchanged.

Acceptance: pm_epic output identical on existing tests; exactly one list_tasks call per pm_epic invocation (verified by US-PRJ-63).

Files: src/projectman/server.py (pm_epic).