---
acceptance_criteria:
- A hub store map lists every subproject with its prefix and store path read from
  projects/{name}/.project/config.yaml and no code path reads .project/projects any
  more
- projectman add-project attaches the submodule's origin/projectman branch as projects/{name}/.project
  when it exists and otherwise creates the orphan branch and scaffolds a fresh store
  there
- projectman migrate-hub moves every .project/projects/{name} store onto that submodule's
  projectman branch worktree and removes the hub copy leaving item files byte-identical
- migrate-hub refuses to run on a dirty hub or subproject tree and is a friendly no-op
  when nothing is left to migrate
- pm_status and the hub rollup report a subproject whose store is not attached as
  not attached instead of raising
created: '2026-09-06'
depends_on: []
epic_id: EPIC-PM-5
id: US-PM-31
points: 8
priority: should
status: done
tags:
- hub
- worktree
- storage
title: Subproject PM data lives at projects/{name}/.project on the repo's own projectman
  branch
updated: '2026-09-06'
---

As a developer working in a hub, I want each subproject's stories, tasks and config to live inside that subproject's checkout on its own `projectman` branch, so that PM data travels with the code it describes and the hub repo stops accumulating every task edit from every project.

Today `_resolve_project_dir` and `_store` in server.py, `hub/rollup.py`, `hub/registry.py`, `indexer.py`, `cli.py` and `web/routes/api.py` all hard-code `.project/projects/{name}/`. Twenty test files build that layout.

Direction: one store map, built in a new `hub/stores.py`, walks `config.projects`, expects `projects/{name}/.project` to be a worktree of that submodule's `projectman` branch (reuse `worktree.attach_worktree` and `worktree.is_worktree`), reads each `config.yaml` and returns name, prefix and path. Every former `.project/projects` reader goes through it. `projectman add-project` attaches `origin/projectman` when it exists and otherwise creates the orphan branch and scaffolds the store, using `_init_subproject`. `projectman migrate-hub` moves each existing `.project/projects/{name}` onto the submodule's branch and removes the hub copy, refusing on a dirty tree like `migrate-worktree` does. Missing or unattached stores show as "not attached" in the rollup rather than raising.