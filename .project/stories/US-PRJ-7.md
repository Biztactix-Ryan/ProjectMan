---
acceptance_criteria:
- Subproject changes create feature branches not direct commits to deploy
- PR creation integrated into workflow (gh cli)
- Hub only updates refs after PRs are merged
- Deploy branch is protected from direct pushes
- Workflow supports simultaneous PRs across multiple subprojects
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-7
points: 8
priority: must
status: done
tags: []
title: Add PR-based workflow for subproject changes into deploy branch
updated: '2026-02-28'
---

As a developer, I want subproject changes to go through pull requests into a deploy branch rather than committing directly so that changes are reviewed and the deploy branch stays stable.

Instead of direct push to tracked branches:
- Create feature branches in subprojects for changes
- Open PRs back into each subproject's deploy/release branch
- Hub tracks the deploy branch, not feature branches
- Coordinated push updates hub refs only after PRs are merged
- Support for auto-creating PRs via `gh pr create` integration

This prevents the "push to wrong branch" problem entirely — you can only merge into deploy via PR, never push directly.