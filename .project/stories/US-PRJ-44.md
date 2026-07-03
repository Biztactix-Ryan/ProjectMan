---
acceptance_criteria:
- pm_batch_update accepts JSON array of update dicts
- Each update applied via store.update with validation
- Single auto-commit for entire batch
- Returns list of updated items or per-item errors
- Proper MCP annotations (destructive=false)
created: '2026-03-09'
epic_id: EPIC-PRJ-8
id: US-PRJ-44
points: 5
priority: must
status: backlog
tags:
- batch
- mcp
title: Implement pm_batch_update MCP tool
updated: '2026-03-09'
---

As a project manager, I want to update multiple items in a single call so that sprint-level operations (mass status changes, bulk reassignment, batch tag updates) are efficient. Currently only single-item pm_update exists. Add pm_batch_update that accepts a JSON array of {id, ...fields} and applies all updates with a single auto-commit.