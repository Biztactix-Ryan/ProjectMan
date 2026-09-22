---
assignee: claude
created: '2026-03-05'
id: US-PRJ-28-8
points: 1
status: done
story_id: US-PRJ-28
title: 'Test: Cache persists across MCP tool invocations'
updated: '2026-03-06'
---

Simulate two sequential MCP tool calls (e.g., pm_board then pm_status). Verify the second call benefits from cache populated by the first.