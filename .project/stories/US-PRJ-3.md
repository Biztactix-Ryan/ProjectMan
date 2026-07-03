---
acceptance_criteria:
- pm_commit tool commits .project/ changes with auto-generated message
- pm_push tool pushes with branch validation
- Hub vs subproject scope is configurable
- Integrates with existing MCP server
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-3
points: 8
priority: should
status: done
tags: []
title: Add pm_commit and pm_push MCP tools for hub-aware git operations
updated: '2026-02-19'
---

As a developer using Claude, I want MCP tools for committing and pushing PM changes so that git operations are integrated into the PM workflow instead of being manual.

Add new MCP tools:
- `pm_commit` — commits .project/ changes in the hub (and optionally subproject PM data)
- `pm_push` — pushes hub and/or subproject changes with pre-push validation
- These tools should be hub-aware: distinguish between hub-level commits and subproject commits
- Hub commits stay on main, subproject commits go to their tracked branches