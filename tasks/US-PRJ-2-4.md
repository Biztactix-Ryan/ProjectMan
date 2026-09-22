---
assignee: claude
created: '2026-02-17'
id: US-PRJ-2-4
points: 3
status: done
story_id: US-PRJ-2
title: Implement validate_branches() core function in hub/registry.py
updated: '2026-02-19'
---

Add a `validate_branches(root)` function to `src/projectman/hub/registry.py` that checks alignment for every registered submodule.

For each project in config.projects[]:
1. Read configured branch from .gitmodules via `git config -f .gitmodules submodule.projects/{name}.branch`
2. Get current HEAD branch via `git rev-parse --abbrev-ref HEAD` in the submodule dir
3. Check for detached HEAD state
4. Check dirty working tree via `git status --porcelain`
5. Compare configured vs actual branch

Return a structured result:
```python
{
  "aligned": [...],      # projects on correct branch
  "misaligned": [...],   # projects on wrong branch (expected vs actual)
  "detached": [...],     # projects in detached HEAD
  "missing": [...],      # registered but dir doesn't exist
  "ok": bool,            # True if all aligned
  "summary": str         # human-readable summary
}
```

Handle edge cases: no .gitmodules entry (branch defaults to remote HEAD), submodule dir missing, not a git repo.

Files: src/projectman/hub/registry.py