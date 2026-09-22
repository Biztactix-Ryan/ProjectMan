---
assignee: claude
created: '2026-02-17'
id: US-PRJ-7-6
points: 2
status: done
story_id: US-PRJ-7
title: Add deploy_branch config to per-subproject config.yaml
updated: '2026-02-28'
---

Extend the subproject config model to include a `deploy_branch` field.

1. Update `src/projectman/models.py` — add `deploy_branch: Optional[str] = None` to ProjectConfig
2. Update `src/projectman/hub/registry.py` — `add_project()` should accept and store `deploy_branch` (defaults to the --branch value or 'main')
3. Update `_init_subproject()` — write deploy_branch to the generated config.yaml
4. Add a `set_deploy_branch(name, branch)` function in registry.py — updates the subproject config (distinct from `set_branch()` which changes .gitmodules tracking)

The deploy branch is the protected target for PRs. The .gitmodules tracked branch should always match deploy_branch — this is the source of truth ProjectMan controls, vs .gitmodules which git controls.

Files: src/projectman/models.py, src/projectman/hub/registry.py, src/projectman/config.py