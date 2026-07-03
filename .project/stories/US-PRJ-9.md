---
acceptance_criteria:
- Deploy branch configurable per subproject in config
- Feature branch naming convention enforced on create
- Direct pushes to deploy branch blocked
- Convention violations produce clear error messages
- Conventions stored in hub config and shared
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-9
points: 5
priority: must
status: backlog
tags: []
title: Enforce opinionated git conventions for hub subprojects
updated: '2026-02-16'
---

As a team using ProjectMan hub mode, I want enforced conventions for how subprojects are managed so that the workflow is predictable and consistent across all repos.

Since ProjectMan already dictates .project/ layout, extend this to git conventions:
- Deploy branch naming: each subproject has a canonical deploy branch (e.g. `main`, `deploy`, configurable per-project in .project/projects/{name}/config.yaml)
- Feature branch naming convention: `pm/{task-id}/{short-description}` (e.g. `pm/US-PRJ-3-1/add-commit-tool`)
- Deploy branch is protected — no direct pushes, PR-only
- Commit message convention for hub submodule ref updates: `hub: update {project} to {short-sha}`
- Validate conventions on push/PR operations, reject violations with clear messages

Store conventions in hub config so they're shared across the team.