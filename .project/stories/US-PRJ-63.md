---
acceptance_criteria:
- test_performance_n1.py created
- Tests verify pm_board uses batch loads not per-task fetches
- Tests verify pm_epic uses single list_tasks call
- Tests verify pm_search tag filter uses batch metadata loading
created: '2026-03-09'
epic_id: EPIC-PRJ-12
id: US-PRJ-63
points: 3
priority: should
status: backlog
tags:
- testing
- performance
title: Add N+1 regression tests for board and epic views
updated: '2026-03-09'
---

As a developer, I want regression tests that detect N+1 query patterns so that performance improvements aren't accidentally reverted. Add tests that verify pm_board doesn't call get_task per task, pm_epic doesn't call list_tasks per story, and pm_search doesn't call get per result.