---
assignee: claude
created: '2026-08-22'
depends_on: []
id: US-PRJ-43-5
points: 2
status: done
story_id: US-PRJ-43
tags: []
title: Load task bodies once in pm_board instead of get_task per task
updated: '2026-08-22'
---

In src/projectman/server.py pm_board currently calls store.get_task(task.id) inside the loop over all_tasks. Each get_task is a linear scan of the cached (meta, body) list, so the board is O(n^2) in task count. Replace with a single pass: use store.list_all (or one iteration over the cached pairs) to build a {task_id: body} map, or iterate the (meta, body) pairs directly, so bodies are fetched exactly once for the whole board.

Acceptance: pm_board output is byte-identical on the existing tests; no get_task call per task (verified by US-PRJ-63); archived-task exclusion and the assignee/tag filters still apply.

Files: src/projectman/server.py (pm_board), possibly src/projectman/store.py if list_all needs a body-bearing variant.