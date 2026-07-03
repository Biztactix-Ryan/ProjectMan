---
assignee: claude
created: '2026-02-17'
id: US-PRJ-3-5
points: 3
status: done
story_id: US-PRJ-3
title: Implement pm_commit() for hub and subproject PM data
updated: '2026-02-19'
---

Add `pm_commit(scope, message=None, root)` to `hub/registry.py`.

Scope options:
- `"hub"` — commits only hub-level .project/ files (stories, tasks, epics, config, dashboards)
- `"project:{name}"` — commits only .project/projects/{name}/ files
- `"all"` — commits all .project/ changes (hub + all subprojects)

Behavior:
1. `git status --porcelain .project/` to find changed PM files
2. Filter to the specified scope
3. `git add` only the scoped files (never add non-.project files)
4. If message is None, auto-generate using convention template from US-PRJ-9: `pm: {action} {ids}` by parsing the changed filenames (e.g. changed US-PRJ-5.md → `pm: update US-PRJ-5`)
5. `git commit -m {message}`
6. Return commit sha and list of committed files

Handle: nothing to commit (return early, don't error), .project/ doesn't exist (error).

Files: src/projectman/hub/registry.py