---
assignee: claude
created: '2026-02-17'
id: US-PRJ-4-7
points: 2
status: done
story_id: US-PRJ-4
title: Implement push_subprojects() for ordered per-project push
updated: '2026-02-20'
---

Add `push_subprojects(projects, root)` that pushes feature branches for each specified subproject.

For each project in the list (order matters — push in the order given):
1. Verify preflight passed for this project (don't re-check, trust the gate)
2. `git push -u origin {current_branch}` in the subproject dir
3. Record result: success (remote ref + sha) or failure (error message)
4. On failure: **stop pushing remaining projects**, report what succeeded and what didn't

Return:
```python
{
    "pushed": [{"name": str, "branch": str, "sha": str}],
    "failed": {"name": str, "error": str} | None,
    "skipped": list[str],   # projects after the failure
    "all_ok": bool
}
```

Stop-on-failure is critical — if project 3 of 5 fails, projects 4 and 5 are skipped rather than silently continuing. The user sees exactly where it broke.

Files: src/projectman/hub/registry.py