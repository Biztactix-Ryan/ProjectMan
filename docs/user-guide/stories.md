# User Stories

## Format

Stories are markdown files in `.project/stories/` with YAML frontmatter:

```yaml
---
id: US-APP-1
title: "User Authentication"
status: backlog
priority: should
points: 8
epic_id: EPIC-APP-1
tags: [backend, security]
created: 2026-01-15
updated: 2026-01-15
---

## User Story

As a **user**, I want **to log in** so that **I can access my account**.

## Acceptance Criteria

- [ ] Users can register with email/password
- [ ] Users can log in and receive a session token
- [ ] Invalid credentials show an error message
```

## Linking to Epics

Stories can be linked to epics via the `epic_id` field. Use `/pm update US-APP-1 --epic-id EPIC-APP-1` or set it during creation.

## Lifecycle

`backlog` → `ready` → `active` → `done` → `archived`

## Best Practices

- Write clear "As a [user], I want [goal] so that [benefit]" descriptions
- Include measurable acceptance criteria
- Keep stories to 13 points or less — decompose larger work. Consider grouping related stories under an epic for large initiatives
- Use priority levels: must, should, could, wont (MoSCoW)
