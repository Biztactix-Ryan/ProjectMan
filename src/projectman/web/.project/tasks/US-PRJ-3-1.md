---
assignee: claude
created: '2026-02-15'
id: US-PRJ-3-1
points: 2
status: done
story_id: US-PRJ-3
title: Create request schemas for create/update operations
updated: '2026-02-15'
---

Create Pydantic request schemas in a new `schemas.py` module:
- `CreateStoryRequest` — title, description, priority, points, epic_id
- `CreateEpicRequest` — title, description, priority, target_date, tags
- `CreateTaskRequest` — story_id, title, description, points
- `UpdateItemRequest` — status, points, title, assignee, epic_id (all optional)
- `GrabTaskRequest` — assignee (optional, defaults to "claude")

Reuse existing Pydantic models from `models.py` wherever possible. Only create thin wrappers where the API shape differs from the storage model. All request schemas should produce clear 422 errors for invalid input.