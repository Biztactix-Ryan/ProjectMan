---
assignee: claude
created: '2026-02-17'
id: US-PRJ-4-6
points: 3
status: done
story_id: US-PRJ-4
title: Implement pre-push preflight check aggregating all validations
updated: '2026-02-20'
---

Add `push_preflight(projects=None, root)` to `hub/registry.py` that runs all checks before any push operation begins.

This is the gate — nothing gets pushed until preflight passes.

Checks to run (composing from other stories):
1. `validate_branches()` (US-PRJ-2) — every submodule on expected branch
2. `validate_conventions()` (US-PRJ-9) — branch naming, deploy protection
3. For each dirty subproject: confirm it has staged changes (not just untracked files)
4. For each subproject to push: confirm remote is reachable (`git ls-remote --exit-code origin`)
5. Confirm `gh` is available if PR workflow is enabled (US-PRJ-7)

Return:
```python
{
    "ready": list[str],       # projects that can be pushed
    "blocked": list[{"name": str, "reason": str}],  # projects that cannot
    "warnings": list[str],    # non-blocking concerns
    "can_proceed": bool       # True only if no blockers
}
```

Abort early on fatal issues (no remote, not a git repo). Collect all non-fatal issues so the user sees everything at once, not one error at a time.

Files: src/projectman/hub/registry.py