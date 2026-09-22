---
acceptance_criteria:
- Changesets group related changes across N repos
- PRs created together with cross-references
- Hub refs update only when all changeset PRs merge
- Partial merge state is clearly reported
- Changeset status visible in git status dashboard
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-10
points: 13
priority: should
status: done
tags: []
title: Add cross-repo changesets for grouped multi-project changes
updated: '2026-02-19'
---

As a developer working on a feature that spans multiple repos, I want to group related changes across subprojects into a single logical changeset so that multi-repo features are tracked and pushed together.

Implement a changeset concept:
- `pm changeset create "feature-name"` — starts tracking changes across repos
- Changes in multiple subprojects are linked to the changeset
- PRs are created together with cross-references (e.g. "Part of changeset: feature-name, see also: org/api#42, org/frontend#18")
- Hub submodule refs are only updated when ALL PRs in the changeset are merged
- If any PR in the changeset fails/is rejected, the others are flagged for review

This prevents partial updates where the API changed but the frontend didn't, leaving the deploy branch broken.