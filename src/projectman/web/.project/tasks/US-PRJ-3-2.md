---
assignee: claude
created: '2026-02-15'
id: US-PRJ-3-2
points: 1
status: done
story_id: US-PRJ-3
title: Create response schemas wrapping existing Pydantic models
updated: '2026-02-15'
---

Create response schemas that wrap existing `StoryFrontmatter`, `TaskFrontmatter`, `EpicFrontmatter` with body content fields:
- `StoryResponse`, `TaskResponse`, `EpicResponse` — include frontmatter fields + body markdown
- `StatusResponse`, `BoardResponse`, `AuditResponse`, `BurndownResponse` — wrap existing tool output formats
- Verify all schemas appear in auto-generated OpenAPI docs at `/docs`