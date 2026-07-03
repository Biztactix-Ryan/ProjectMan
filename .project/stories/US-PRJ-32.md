---
acceptance_criteria:
- pm_board avoids per-task get_task() body reads where possible
- Readiness checks use pre-loaded story and sibling data instead of per-task lookups
- Total file I/O for 100 tasks reduced by at least 50%
- All board tests pass with same output
- Performance test added for 100+ task board
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-32
points: 5
priority: should
status: backlog
tags:
- tier-2
- performance
title: Reduce pm_board N+1 I/O pattern
updated: '2026-03-06'
---

As a user, I want pm_board to be fast on large projects so that I don't wait seconds for the board to render. Currently pm_board does per-task file reads for bodies and per-task readiness checks that each call get_story() and list_tasks(), resulting in ~300 file I/O operations for 100 tasks.