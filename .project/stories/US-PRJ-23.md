---
acceptance_criteria:
- Tasks with incomplete deps appear in not_ready on board
- Board available section sorted by topological order within each story
- pm_grab returns error when task has incomplete dependencies
- pm_grab includes dependency_status in response showing dep titles and statuses
- Readiness blocker message lists specific incomplete dep IDs
created: '2026-02-23'
epic_id: EPIC-PRJ-4
id: US-PRJ-23
points: 5
priority: must
status: done
tags: []
title: Readiness and board dependency integration
updated: '2026-03-01'
---

As a user, I want pm_board to show tasks in dependency order and pm_grab to block when prerequisites aren't done so that I always work on unblocked tasks first.

Covers: adding dependency hard blocker to readiness.py check_readiness(), updating pm_board sort to use topological order within stories, and adding dependency_status to pm_grab response.