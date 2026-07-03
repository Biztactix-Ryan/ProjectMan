---
acceptance_criteria:
- Deep copies removed from all list/get cache returns
- Benchmark shows 10x+ improvement for 1000-item lists
- No mutation side effects from removing deep copy
- Regression tests confirm cache integrity
created: '2026-03-09'
epic_id: EPIC-PRJ-7
id: US-PRJ-37
points: 5
priority: must
status: active
tags:
- performance
- caching
title: Eliminate deep copy overhead on cached reads
updated: '2026-03-09'
---

As a developer working on large projects, I want cached reads to avoid unnecessary deep copying so that list operations are fast even with 1000+ items. Currently store.py lines 285, 371, 394-395, 444, 484, 507-508, 701, 739 all deep copy entire result sets on every retrieval. Pydantic models are effectively immutable so deep copy is unnecessary.