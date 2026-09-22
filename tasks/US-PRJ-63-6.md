---
assignee: claude
created: '2026-08-22'
depends_on:
- US-PRJ-63-5
- US-PRJ-43-5
- US-PRJ-43-6
- US-PRJ-43-7
- US-PRJ-43-8
id: US-PRJ-63-6
points: 2
status: done
story_id: US-PRJ-63
tags: []
title: Assert pm_board, pm_epic and pm_search make batch loads, not per-item calls
updated: '2026-08-22'
---

Using the fixtures from US-PRJ-63-5, add regression tests that pin the N+1 fixes from US-PRJ-43:
- pm_board on the 100-task project makes zero Store.get_task calls and at most one list_tasks and one list_stories call (US-PRJ-43-5, US-PRJ-43-6).
- pm_epic on an epic with 10+ stories makes exactly one list_tasks call (US-PRJ-43-7).
- pm_search with a tag filter makes zero Store.get calls per result (US-PRJ-43-8); use the keyword-search path or a stubbed EmbeddingStore so the test does not need the embedding model.
- pm_active makes exactly one list_stories call with a tag filter (US-PRJ-43-8).

Each assertion message should name the tool and the call it is guarding so a future regression is self-explanatory.

Acceptance: all four tests pass against the US-PRJ-43 implementation and fail if the per-item calls are reintroduced.

Files: tests/test_performance_n1.py.