---
assignee: claude
created: '2026-02-17'
id: US-PRJ-8-6
points: 2
status: done
story_id: US-PRJ-8
title: Add PR status collection via gh cli
updated: '2026-02-28'
---

Extend git_status_all() output with open PR data per subproject.

For each project, query GitHub via:
`gh pr list --repo {owner/repo} --base {deploy_branch} --state open --json number,title,headRefName,isDraft,updatedAt --limit 10`

Add to each project's status:
```python
{
    "open_prs": int,
    "prs": [
        {"number": int, "title": str, "branch": str, "draft": bool, "updated": str}
    ]
}
```

Get repo URL from subproject's `git remote get-url origin` or from the config if stored.

Handle: gh not installed (skip PR data, add warning), gh not authenticated (skip, warn), no GitHub remote (skip, note as non-GitHub repo). PR collection should be opt-in or fail gracefully — never block the core git status.

Files: src/projectman/hub/registry.py