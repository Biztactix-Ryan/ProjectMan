# Epics

Epics are strategic initiatives that group related stories. They are first-class entities stored in `.project/epics/` with YAML frontmatter, just like stories and tasks.

## Creating an Epic

```
/pm create epic "Unified Authentication" "Single sign-on across all services"
```

Or via MCP: `pm_create_epic(title, description, priority?, target_date?, tags?)`

This creates an epic file like `EPIC-API-1.md` in `.project/epics/`.

## Epic Format

```yaml
---
id: EPIC-API-1
title: "Unified Authentication"
status: draft
priority: must
points: null
target_date: '2026-06-30'
tags: [security, mvp]
created: '2026-02-15'
updated: '2026-02-15'
---

## Vision

Single sign-on across all services by Q2.

## Success Criteria

- [ ] Users can log in once and access all services
- [ ] JWT tokens are validated across all backends
- [ ] Session timeout is consistent (30 min)
```

## Epic Lifecycle

```
draft → active → done → archived
```

1. **Draft** -- write the epic with vision and success criteria
2. **Active** -- stories are being created and worked on
3. **Done** -- all linked stories are complete
4. **Archived** -- historical record

## Linking Stories to Epics

Stories link to epics via the `epic_id` frontmatter field:

```yaml
---
id: US-API-5
title: Backend auth service
epic_id: EPIC-API-1
status: active
---
```

Link during creation:
```
pm_create_story(title, description, epic_id="EPIC-API-1")
```

Or link an existing story:
```
pm_update("US-API-5", epic_id="EPIC-API-1")
```

## Viewing Epic Progress

Get full epic rollup with linked stories and completion percentage:

```
pm_epic("EPIC-API-1")
```

Returns the epic details plus:
- Linked stories with their tasks (paginated, default 10 per page)
- Total and completed points (rollup always covers all stories)
- Completion percentage
- `has_more` / `next_offset` for pagination when there are many stories

Use `limit` and `offset` to page through large epics:
```
pm_epic("EPIC-API-1", limit=10, offset=10)
```

## Cross-Repo Epics (Hub Mode)

In hub mode, epics can span multiple projects. Create the epic in the hub's `.project/epics/`, then link stories from different subprojects:

```
# Create epic at hub level
pm_create_epic("Unified Auth", "Cross-service authentication")

# Link stories from different projects
pm_update("US-API-5", epic_id="EPIC-HUB-1")  # in my-api project
pm_update("US-FE-3", epic_id="EPIC-HUB-1")   # in my-frontend project
```

## Audit Checks

The audit system validates epic consistency:

- **Empty active epic** [WARNING] -- active epic with no linked stories
- **Done epic with open stories** [ERROR] -- epic marked done but stories still open
- **Orphaned epic reference** [WARNING] -- story references non-existent epic
- **Stale draft epic** [INFO] -- draft epic with no stories for 30+ days

## Best Practices

- Keep epics focused on a clear strategic goal
- Link all related stories to their epic for tracking
- Use `pm_epic(id)` to review progress regularly
- Move epics to done only when all linked stories are complete
- Archive completed epics to keep the board clean
