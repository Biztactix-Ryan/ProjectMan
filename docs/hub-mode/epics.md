# Cross-Repo Epics

Epics are large initiatives that span multiple projects. They live in the hub's `roadmap/` directory as markdown files and link to stories across your repos.

## Creating an Epic

Create a markdown file in your hub's `roadmap/` directory:

```markdown
# Epic: Unified Authentication

## Goal
Single sign-on across all services by Q2.

## Stories

| Project | Story | Title | Status |
|---------|-------|-------|--------|
| my-api | API-5 | Backend auth service | active |
| my-api | API-6 | JWT middleware | backlog |
| my-frontend | FE-3 | Login UI | backlog |
| my-frontend | FE-4 | Session management | backlog |
| my-mobile | MOB-2 | Biometric login | backlog |

## Acceptance Criteria
- [ ] Users can log in once and access all services
- [ ] JWT tokens are validated across all backends
- [ ] Session timeout is consistent (30 min)

## Notes
Depends on API-5 completing first — frontend and mobile work blocked until
the auth service is deployed.
```

## Epic Lifecycle

1. **Draft** — write the epic with a goal and rough story list
2. **Scope** — use `/pm-scope` on each linked story to break into tasks
3. **Estimate** — sum story points across all linked stories for total effort
4. **Track** — check progress with `pm_status` for each project
5. **Close** — when all linked stories are done, mark the epic complete

## Tracking Epic Progress

Hub-wide status (all projects):
```
/pm-status
```

Single project within the hub:
```
pm_status(project="my-api")
```

Cross-repo burndown:
```
/pm-burndown
```

## Linking Stories to Epics

Stories reference their epic in the frontmatter tags:

```yaml
---
id: API-5
title: Backend auth service
tags: [epic:unified-auth]
---
```

This lets you search for all stories in an epic:
```
pm_search("epic:unified-auth")
```

## Best Practices

- Keep epics focused — if it spans more than 4-5 repos, consider splitting
- Identify cross-repo dependencies early and note them in the epic
- Review epic progress weekly during sprint planning
- Archive completed epics by moving them to `roadmap/archive/`
