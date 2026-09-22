---
assignee: claude
created: '2026-03-05'
id: US-PRJ-28-10
points: 1
status: done
story_id: US-PRJ-28
title: 'Test: Cache hit behavior across sequential tool calls'
updated: '2026-03-06'
---

Integration test: call pm_status, pm_board, pm_get in sequence on same server instance. Instrument cache to count disk reads — should be at most 1 full load, not 3.