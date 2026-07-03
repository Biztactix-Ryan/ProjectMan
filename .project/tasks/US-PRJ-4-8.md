---
assignee: claude
created: '2026-02-17'
id: US-PRJ-4-8
points: 2
status: done
story_id: US-PRJ-4
title: Implement push_hub() for hub ref commit and push
updated: '2026-02-20'
---

Add `push_hub(pushed_projects, root)` that updates hub submodule refs and pushes the hub.

This only runs AFTER all subprojects pushed successfully:
1. For each pushed project: `git add projects/{name}` (stages the updated submodule ref)
2. Generate commit message using convention template: `hub: update {project1}, {project2}, ... to {sha1[:7]}, {sha2[:7]}, ...` (or individual commits per project if preferred)
3. `git commit` with the formatted message
4. `git push origin main` (hub is always on main)
5. If hub push fails (conflict with another developer): report the conflict, do NOT force push, suggest `git pull --rebase` and retry

Return:
```python
{
    "committed": bool,
    "pushed": bool,
    "commit_sha": str | None,
    "error": str | None
}
```

If hub push fails, the subproject pushes already succeeded — that's fine. The subproject code is on the remote. The user just needs to resolve the hub conflict and re-push the hub.

Files: src/projectman/hub/registry.py