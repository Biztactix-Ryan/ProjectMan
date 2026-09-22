---
acceptance_criteria:
- Single command pushes across hub + N subprojects
- Validates branch alignment before any push
- Subprojects pushed before hub ref update
- Clear report of what succeeded/failed
- No silent partial pushes
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-4
points: 8
priority: must
status: done
tags: []
title: Add coordinated multi-project push command
updated: '2026-02-20'
---

As a developer, I want a single command to safely commit and push changes across the hub and multiple subprojects so that multi-project updates are atomic and coordinated.

Implement a `push-all` or coordinated push workflow:
- Validate all submodules are on correct branches (pre-push check)
- Commit subproject changes first (each on their own branch)
- Push subproject changes
- Update hub submodule refs to point to new commits
- Commit and push hub
- If any step fails, report clearly what succeeded and what didn't (no silent partial pushes)