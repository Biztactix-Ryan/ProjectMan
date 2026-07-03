---
assignee: null
created: '2026-02-17'
id: US-PRJ-9-6
points: 2
status: todo
story_id: US-PRJ-9
title: Add hub-level conventions config schema
updated: '2026-02-17'
---

Define a conventions block in the hub's `.project/config.yaml` that all subprojects inherit.

Add to `src/projectman/models.py`:
```python
class HubConventions(BaseModel):
    branch_prefix: str = "pm"                          # feature branches: {prefix}/{task-id}/{slug}
    deploy_branch_default: str = "main"                 # default if subproject doesn't override
    commit_msg_hub_ref: str = "hub: update {project} to {sha}"  # template for hub ref commits
    commit_msg_pm: str = "pm: {action} {id}"            # template for PM data commits
    require_pr: bool = True                             # enforce PR-only into deploy branch
```

Update `ProjectConfig` to include `conventions: Optional[HubConventions] = None` (only populated in hub mode).

Update `src/projectman/config.py` to load/save conventions. Subproject configs inherit hub conventions but can override `deploy_branch` locally.

This is the central source of truth — US-PRJ-7 tasks (deploy_branch, branch naming) should read from this.

Files: src/projectman/models.py, src/projectman/config.py