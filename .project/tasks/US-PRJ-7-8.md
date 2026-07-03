---
assignee: claude
created: '2026-02-17'
id: US-PRJ-7-8
points: 3
status: done
story_id: US-PRJ-7
title: Implement create_pr() wrapping gh cli for subproject PRs
updated: '2026-02-28'
---

Add PR creation that targets the deploy branch via `gh` CLI.

`create_pr(project_name, title, body, root, draft=False)` in `hub/registry.py`:
1. Detect current feature branch in the subproject
2. Validate it's a `pm/*` branch (not deploy branch — block direct push)
3. Push the feature branch to remote: `git push -u origin {branch}`
4. Create PR via: `gh pr create --base {deploy_branch} --head {feature_branch} --title ... --body ...`
5. Return PR URL and number

Also add `get_pr_status(project_name, root)` — checks open PRs targeting deploy branch via `gh pr list --base {deploy_branch} --json number,title,state,headRefName`

Handle: gh not installed (clear error), not authenticated (clear error), no remote (clear error).

Files: src/projectman/hub/registry.py