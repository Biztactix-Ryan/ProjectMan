---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-39-6
- US-PM-40-3
id: US-PM-39-7
points: 3
status: done
story_id: US-PM-39
tags: []
title: Route all 26 endpoints through the resolver and delete the project query parameter
updated: '2026-09-07'
---

Replace `Depends(get_store)` / `Depends(get_project_dir)` and every `project: Optional[str] = Query(None)` in src/projectman/web/routes/api.py. ID routes (get item, update, archive, epic rollup, run log, task claim if present) take the store from the ID. ID-less routes (status, board, burndown, search, list epics/stories/tasks, create story/task/epic, audit) take `prefix`. GET /api/status keeps its `subprojects` list when no prefix is given in a hub. Update src/projectman/web/README.md. Confirm with grep that `project` no longer appears as a Query in api.py and that tests/web and tests/test_server.py pass. Front-end JS sends no project= today; verify with grep and leave it alone.