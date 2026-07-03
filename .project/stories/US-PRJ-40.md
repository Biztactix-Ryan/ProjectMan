---
acceptance_criteria:
- Dirty flag tracks which item types changed since last rebuild
- Only affected markdown index files are regenerated
- Full rebuild still available as fallback
- Hub README rebuild skips unchanged subprojects
created: '2026-03-09'
epic_id: EPIC-PRJ-7
id: US-PRJ-40
points: 8
priority: could
status: backlog
tags:
- performance
- indexer
title: Add incremental index rebuilds with dirty tracking
updated: '2026-03-09'
---

As a developer, I want index rebuilds to only process changed items so that pm_status and write_index are fast. Currently indexer.py lines 31-106 rebuild the entire index every time. Add dirty-tracking to detect what changed and only regenerate affected markdown files.