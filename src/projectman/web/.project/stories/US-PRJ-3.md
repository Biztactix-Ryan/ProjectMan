---
created: '2026-02-15'
epic_id: EPIC-PRJ-1
id: US-PRJ-3
points: 3
priority: must
status: done
tags: []
title: Request/response schemas
updated: '2026-02-15'
---

As a developer, I want API-specific Pydantic schemas so that request validation and response serialization are clean and documented.

**Schemas to create:**
- `CreateStoryRequest` — title, description, priority, points, epic_id (all optional except title/description)
- `CreateEpicRequest` — title, description, priority, target_date, tags
- `CreateTaskRequest` — story_id, title, description, points
- `UpdateItemRequest` — status, points, title, assignee, epic_id (all optional)
- `GrabTaskRequest` — assignee (optional, defaults to "claude")
- Response schemas wrapping existing `StoryFrontmatter`, `TaskFrontmatter`, `EpicFrontmatter` with body content

**Reuse existing Pydantic models from `models.py`** wherever possible. Only create thin wrappers where the API shape differs from the storage model.

**Acceptance criteria:**
- All create/update endpoints validate input via Pydantic schemas
- Invalid requests return 422 with clear error messages
- OpenAPI schema shows all request/response types