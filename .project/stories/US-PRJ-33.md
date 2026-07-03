---
acceptance_criteria:
- pm_epic loads all tasks once then filters by story_id in memory
- File I/O reduced from N list_tasks calls to 1
- All epic tests pass
- Performance acceptable for epics with 20+ stories
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-33
points: 3
priority: should
status: backlog
tags:
- tier-2
- performance
title: Batch list_tasks in pm_epic to eliminate N² queries
updated: '2026-03-06'
---

As a user, I want pm_epic to be efficient so that epics with many stories don't cause excessive file scanning. Currently pm_epic calls list_tasks(story_id) per linked story, resulting in N separate glob+parse operations.