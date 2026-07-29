---
assignee: null
created: '2026-07-30'
depends_on: []
id: US-PRJ-37-6
points: 3
status: todo
story_id: US-PRJ-37
tags: []
title: Add cache-integrity regression tests for list/get returns
updated: '2026-07-30'
---

Cover the remaining acceptance criteria: no mutation side effects from removing deep copy, and cache integrity holds. Tests should assert that mutating a returned model or list does not corrupt subsequent reads from the same cache generation, that cache invalidation on write still yields fresh data, and that repeated reads are consistent. Satisfies US-PRJ-37-3 and US-PRJ-37-4.