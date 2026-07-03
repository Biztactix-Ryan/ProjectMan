---
acceptance_criteria:
- Config option to enable/disable auto-commit
- Auto-generated commit messages from PM operations
- Only commits .project/ files touched by the mutation
- Does not auto-push
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-5
points: 5
priority: could
status: done
tags: []
title: Add auto-commit option for PM mutations
updated: '2026-02-20'
---

As a developer, I want an option to auto-commit PM changes after mutations (story/task create/update) so that PM data is always tracked in git without manual intervention.

Add configurable auto-commit behavior:
- Config option in .project/config.yaml: `auto_commit: true/false`
- When enabled, each PM mutation (create story, update task, etc.) automatically commits the changed files
- Commit messages are auto-generated from the operation (e.g., "pm: create story US-PRJ-5")
- Does NOT auto-push (push remains explicit to avoid surprises)