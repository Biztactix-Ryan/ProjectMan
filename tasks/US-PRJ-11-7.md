---
assignee: claude
created: '2026-02-17'
id: US-PRJ-11-7
points: 3
status: done
story_id: US-PRJ-11
title: Implement auto-rebase for hub push conflicts
updated: '2026-02-19'
---

Add `hub_push_with_rebase(max_retries=3, root)` to `hub/registry.py`.

When `git push origin main` fails due to remote being ahead:
1. `git fetch origin main`
2. Analyze the conflict:
   a. If only submodule refs changed (no .project/ file conflicts) → auto-rebase is safe
   b. If .project/ files also changed → auto-rebase may work but needs merge check
3. `git rebase origin/main`
4. If rebase succeeds cleanly → retry push
5. If rebase has conflicts:
   a. Submodule ref conflict on same project → check if fast-forwardable (see next task)
   b. .project/ file conflict → abort rebase, flag for manual resolution
6. Retry up to max_retries times (covers the case where someone else pushes during our rebase)

Return:
```python
{
    "pushed": bool,
    "retries": int,
    "rebased": bool,
    "error": str | None
}
```

Files: src/projectman/hub/registry.py