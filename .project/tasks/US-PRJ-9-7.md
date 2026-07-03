---
assignee: null
created: '2026-02-17'
id: US-PRJ-9-7
points: 3
status: todo
story_id: US-PRJ-9
title: Implement validate_conventions() unified checker
updated: '2026-02-17'
---

Add a single validation function that checks all conventions at once.

`validate_conventions(project_name, operation, root)` in `hub/registry.py`:

The `operation` parameter controls what's checked:
- `"branch"` — validate current branch follows naming convention (`pm/{task-id}/{slug}` for feature work, deploy branch for sync/pull)
- `"commit"` — validate commit message matches convention template
- `"push"` — validate not pushing directly to deploy branch (must PR)
- `"all"` — run all checks

Return structured result:
```python
{
    "valid": bool,
    "violations": [
        {"rule": str, "expected": str, "actual": str, "severity": "error"|"warning"}
    ],
    "message": str  # human-readable summary
}
```

Error messages must be clear and actionable: "Branch 'feature-x' doesn't follow convention. Expected format: pm/{task-id}/{description}. Run `projectman create-branch {task-id}` to create a properly named branch."

Files: src/projectman/hub/registry.py