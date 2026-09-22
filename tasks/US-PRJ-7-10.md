---
assignee: claude
created: '2026-02-17'
id: US-PRJ-7-10
points: 2
status: done
story_id: US-PRJ-7
title: Add deploy branch protection validation
updated: '2026-02-28'
---

Implement guardrails that prevent direct pushes to deploy branches.

1. Add `validate_not_on_deploy_branch(project_name, root)` — returns error if the subproject's HEAD is on the deploy branch and there are staged/uncommitted changes (you should be on a feature branch)

2. Wire into existing operations:
   - `sync()` is exempt (it pulls into deploy, which is correct)
   - Any future `push()` or `commit()` operation should call this check first
   - `create_pr()` already validates you're on a pm/* branch

3. Optionally support GitHub branch protection rules setup via `gh api`: `gh api repos/{owner}/{repo}/branches/{deploy_branch}/protection -X PUT` — but this is a suggestion/docs task, not enforced locally since it requires repo admin access.

Files: src/projectman/hub/registry.py