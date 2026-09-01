---
assignee: claude
created: '2026-08-22'
depends_on:
- US-PRJ-43-5
id: US-PRJ-43-6
points: 2
status: done
story_id: US-PRJ-43
tags: []
title: Let check_readiness accept pre-loaded context and pass it from pm_board
updated: '2026-08-22'
---

src/projectman/readiness.py check_readiness() calls store.get_story(), store.list_tasks() and store.list_stories() on every invocation. pm_board calls it per task, so a 100-task board re-runs those three lookups 100 times. Add optional keyword arguments (e.g. stories: dict[str, StoryFrontmatter] | None, all_tasks: list | None, all_stories: list | None); when supplied, use them instead of hitting the store. Leave the store-backed path as the default so pm_grab, pm_done_next and other single-task callers are unchanged.

Then have pm_board build the story dict and task/story lists once and pass them in.

Acceptance: readiness results are unchanged on existing tests; pm_board makes at most one list_tasks and one list_stories call regardless of task count.

Files: src/projectman/readiness.py, src/projectman/server.py (pm_board).