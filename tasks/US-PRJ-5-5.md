---
assignee: claude
created: '2026-02-17'
id: US-PRJ-5-5
points: 1
status: done
story_id: US-PRJ-5
title: Add auto_commit config option to ProjectConfig
updated: '2026-02-20'
---

Extend config to support auto-commit toggle.

1. Add `auto_commit: bool = False` to `ProjectConfig` in `src/projectman/models.py`
2. Update `src/projectman/config.py` to load/save auto_commit from .project/config.yaml
3. In hub mode, auto_commit in hub config applies to hub-level PM data. Subproject configs can override independently.

Config example:
```yaml
name: my-hub
hub: true
auto_commit: true   # auto-commit PM changes in hub
projects:
  - api
  - web
```

Files: src/projectman/models.py, src/projectman/config.py