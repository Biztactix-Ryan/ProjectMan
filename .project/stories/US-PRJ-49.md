---
acceptance_criteria:
- pm_fix_malformed marked destructiveHint=True
- pm_restore marked destructiveHint=True
- pm_push and pm_push_all marked destructiveHint=True
- All other tools reviewed for correct annotations
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-49
points: 1
priority: must
status: backlog
tags:
- quality
- mcp
title: Fix destructive annotations on mutation tools
updated: '2026-03-09'
---

As an MCP client, I want accurate destructive hints so that I can warn users appropriately. Currently only pm_archive is marked destructive=True, but pm_fix_malformed, pm_restore, pm_push, and pm_push_all all modify remote state or move files and should also be marked destructive.