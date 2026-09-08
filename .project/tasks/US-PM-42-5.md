---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-42-5
points: 3
status: done
story_id: US-PM-42
tags: []
title: Extend the Unreleased changelog section to cover Sprints 7 to 12
updated: '2026-09-08'
---

Read the closed stories of Sprints 7 to 12 (pm_list_sprints then pm_batch_get on their planned_stories) and the existing Unreleased section of CHANGELOG.md, which stops at 2026-09-02. Add entries under Added, Changed and Removed for: orphan-branch worktree storage plus init attach and the attach command (US-PM-19, 20, 21); the subtraction epic EPIC-PM-4 (changesets and hub PR workflow removed, pm_next and /pm-next, store never overwrites on create, a write dirties only the item file plus the activity log, pm-orchestrate skill under 9KB, unused tool families behind config flags); the hub redesign EPIC-PM-5 (PM data at projects/{name}/.project on each repo's projectman branch, the project argument dropped from every tool and the ID prefix routes instead, the hub is a read-only rollup, epics at hub level only, migrate-hub); Sprint 12 (web API routes by prefix and drops ?project=, hub/dashboards.py removed, keyword search skips a malformed file, hub troubleshooting guide, template-history tests pin a commit). Keep the Keep a Changelog style already in the file. Update the date range line.