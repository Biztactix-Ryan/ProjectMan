---
assignee: claude
created: '2026-03-06'
depends_on: []
id: US-PRJ-29-8
points: 1
status: done
story_id: US-PRJ-29
tags: []
title: Verify cycle error messages show full path end-to-end
updated: '2026-03-09'
---

After refactoring, confirm that cycle errors from create_task, create_tasks, and update all show the full cycle path (e.g. 'A -> B -> C -> A') instead of just the last edge. Update any tests that assert on the old partial error message format.