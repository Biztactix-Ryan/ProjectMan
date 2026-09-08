---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-44-6
- US-PM-45-5
- US-PM-45-6
- US-PM-45-7
id: US-PM-46-6
points: 1
status: done
story_id: US-PM-46
tags: []
title: Drop the hub and projects config fields and tolerate them in legacy files
updated: '2026-09-08'
---

In src/projectman/models.py remove ProjectConfig.hub and ProjectConfig.projects; make load_config ignore those two keys if a legacy config.yaml still carries them (a warning is acceptable, an error is not). Remove them from src/projectman/templates/config.yaml.j2 and the config.yaml section of docs/reference/file-formats.md. Remove hub: false / projects: [] from the scaffold that projectman init writes. Do not edit this repo's own .project/config.yaml. Add a test loading a config.yaml with hub: true and projects: [x]. Run tests/test_config.py and tests/test_cli.py.