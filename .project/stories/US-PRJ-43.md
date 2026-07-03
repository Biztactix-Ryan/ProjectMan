---
acceptance_criteria:
- pm_board uses list_all or cache for task bodies instead of per-task get
- pm_epic pre-fetches all tasks and partitions by story_id locally
- pm_search tag filter batch-loads metadata instead of individual gets
- pm_active removes redundant list_stories call on line 252
created: '2026-03-09'
epic_id: EPIC-PRJ-8
id: US-PRJ-43
points: 5
priority: must
status: backlog
tags:
- batch
- performance
title: Fix N+1 patterns in pm_board, pm_epic, pm_search
updated: '2026-03-09'
---

As a user viewing boards and epics, I want these views to load efficiently so that large projects feel responsive. pm_board (server.py:366) fetches task bodies one-by-one in a loop. pm_epic (server.py:588) calls list_tasks per story. pm_search (server.py:302) calls store.get() per search result for tag filtering. All should pre-fetch data in batch.