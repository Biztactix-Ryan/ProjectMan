---
assignee: claude
created: '2026-02-17'
id: US-PRJ-8-5
points: 3
status: done
story_id: US-PRJ-8
title: Implement git_status_all() core data collection
updated: '2026-02-28'
---

Add `git_status_all(root)` to `src/projectman/hub/registry.py` that gathers git state for every registered submodule.

For each project in config.projects[], collect:
1. **Branch info**: `git rev-parse --abbrev-ref HEAD` — current branch. Compare against deploy_branch from conventions config (US-PRJ-9-6) or .gitmodules tracking.
2. **Working tree**: `git status --porcelain` — dirty/clean, count of modified/untracked files
3. **Ahead/behind**: `git rev-list --left-right --count {branch}...origin/{branch}` — commits ahead and behind remote
4. **Last commit**: `git log -1 --format=%H|%ai|%an|%s` — sha, date, author, message
5. **Detached HEAD**: detect via rev-parse returning 'HEAD'

Return structured list:
```python
[
    {
        "name": str,
        "branch": str,
        "deploy_branch": str,
        "aligned": bool,
        "dirty": bool,
        "dirty_count": int,
        "ahead": int,
        "behind": int,
        "detached": bool,
        "last_commit": {"sha": str, "date": str, "author": str, "message": str},
        "issues": list[str]   # human-readable list of problems
    }
]
```

Run git commands in parallel (subprocess per project) for performance at 20+ repos. Handle missing dirs, not-a-repo, and no remote gracefully.

Files: src/projectman/hub/registry.py