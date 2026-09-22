---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PRJ-55-9
points: 2
status: done
story_id: US-PRJ-55
tags: []
title: Write docs/hub-mode/troubleshooting.md for the projects/{name}/.project layout
updated: '2026-09-07'
---

Symptom, cause, fix for each: (1) pm_status / rollup / GET /api/status shows a subproject as `not attached` with a hint, fix `projectman sync` (registry._attach_missing_store); (2) `projectman migrate-hub` refuses on a dirty hub or subproject tree, and its no-op wording when .project/projects/ is already empty (hub/migrate.py); (3) a submodule whose projectman branch has no remote so pm_push(prefix) reports nowhere to push, fix push the branch once by hand; (4) a story whose epic_id resolves in neither the hub store nor its own store, what pm_audit and pm_update say and how to relink; (5) a submodule pointer behind the store's branch after someone else pushed, fix `projectman sync` then commit the pointer. Read the actual error strings from hub/stores.py, hub/migrate.py, hub/registry.py and worktree.py and quote them. Do not mention repair, coordinated push, validate-branches, or changesets.