---
assignee: claude
created: '2026-02-17'
id: US-PRJ-7-7
points: 2
status: done
story_id: US-PRJ-7
title: Implement create_feature_branch() for task-linked branching
updated: '2026-02-28'
---

Add a function to create properly-named feature branches in subprojects.

`create_feature_branch(project_name, task_id, description, root)` in `hub/registry.py`:
1. Validate the subproject exists and is on its deploy branch
2. Create branch with convention: `pm/{task_id}/{slugified-description}` (e.g. `pm/US-API-3-1/add-auth-endpoint`)
3. Run `git checkout -b {branch_name}` in the subproject dir
4. Return the branch name for use in subsequent operations

Also add `list_feature_branches(project_name, root)` — lists all `pm/*` branches in a subproject so we can track what's in flight.

Validation: refuse to create if working tree is dirty (must commit or stash first). Refuse to branch from anything other than deploy branch (keeps the tree clean).

Files: src/projectman/hub/registry.py