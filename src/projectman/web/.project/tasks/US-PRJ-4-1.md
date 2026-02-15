---
assignee: claude
created: '2026-02-15'
id: US-PRJ-4-1
points: 1
status: done
story_id: US-PRJ-4
title: Add web optional dependency group to pyproject.toml
updated: '2026-02-15'
---

Add `web` optional dependency group to `pyproject.toml`:
```toml
[project.optional-dependencies]
web = ["fastapi>=0.115", "uvicorn[standard]>=0.34"]
```
Verify installable with `pip install -e ".[web]"` from repo root.