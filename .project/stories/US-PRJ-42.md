---
acceptance_criteria:
- All stories/tasks/epics loaded once at audit start
- 15 checks run against pre-loaded data
- No repeated list_stories or get_story calls
- Duplicate doc check logic extracted to shared function
created: '2026-03-09'
epic_id: EPIC-PRJ-7
id: US-PRJ-42
points: 3
priority: should
status: backlog
tags:
- performance
- audit
title: Fix N+1 audit queries with pre-loaded data
updated: '2026-03-09'
---

As a developer, I want audit checks to run efficiently so that pm_audit is fast on large projects. Currently audit.py lines 155, 166, 191 call store.list_stories() repeatedly (3+ times). Lines 74-90 re-parse story bodies from disk despite cache. Should pre-load all data once, then run all 15 checks against in-memory data.