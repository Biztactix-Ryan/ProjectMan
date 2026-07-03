---
acceptance_criteria:
- _cache_stats invalidations counter only tracks true invalidations
- Changesets cached following same pattern as stories/epics/tasks
- Single-threaded cache assumption documented in store.py
- Duplicate depends_on entries deduplicated in model validator
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-36
points: 3
priority: could
status: backlog
tags:
- tier-3
- caching
- polish
title: Cache and documentation polish
updated: '2026-03-06'
---

As a developer, I want the caching system to have accurate debug stats, consistent coverage, and documented assumptions so that future maintenance is easier. Covers: fix _cache_stats naming, add changeset caching, document single-threaded assumption, deduplicate depends_on entries.