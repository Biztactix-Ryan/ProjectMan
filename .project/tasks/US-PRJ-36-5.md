---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-36-5
points: 1
status: todo
story_id: US-PRJ-36
tags: []
title: Fix _cache_stats counter naming and tracking
updated: '2026-03-06'
---

Rename _cache_stats['invalidations'] to 'mutations' (or add separate 'appends', 'updates', 'invalidations' counters). Only count true cache clears as invalidations. Update store.py lines 23, 30, 300, 308, 331.