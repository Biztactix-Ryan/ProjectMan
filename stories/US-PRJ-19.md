---
acceptance_criteria:
- pm_activity tool registered and callable via MCP
- Supports filtering by item_id and event_type and date range
- Returns formatted human-readable output with timestamps
- Handles empty or missing log file gracefully
- Pagination via limit/offset parameters
created: '2026-02-17'
epic_id: EPIC-PRJ-3
id: US-PRJ-19
points: 3
priority: must
status: done
tags: []
title: MCP tool for querying activity log
updated: '2026-03-01'
---

As a user, I want to query the activity log through MCP tools so that I can see what happened, when, and by whom — filtered by item, date, or event type.

Add a `pm_activity` MCP tool that reads the JSONL log and returns formatted results. Support filtering by: item ID (show all changes to US-PRJ-1), event type (all "created" events), date range, and actor. Default to showing recent activity (last 20 entries). Output should be human-readable with timestamps.