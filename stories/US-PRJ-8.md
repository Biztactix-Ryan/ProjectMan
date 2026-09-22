---
acceptance_criteria:
- Single command shows git state of all N submodules
- Shows branch/dirty/ahead-behind/PR status per repo
- Highlights mismatches and issues
- Scales to 20+ submodules without clutter
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-8
points: 5
priority: must
status: done
tags: []
title: Add hub git status dashboard across all submodules
updated: '2026-02-28'
---

As a developer managing N submodules, I want a single command that shows the git state of every subproject so that I can instantly see what needs attention.

Implement a `pm_git_status` or `projectman git-status` command that shows for each submodule:
- Current branch vs tracked branch (highlight mismatches)
- Dirty/clean working tree
- Ahead/behind remote counts
- Open PR count (via gh cli)
- Last commit date/author

Output should be a compact table, sorted by "needs attention" priority. This is the first thing you run before any coordinated operation.

Since we dictate project layout, we can enforce that all submodules live under projects/ and follow our conventions.