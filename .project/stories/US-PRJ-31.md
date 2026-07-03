---
acceptance_criteria:
- pm_board output includes note distinguishing blocked vs not_ready
- Board tool docstring clarifies the distinction
- Forward references in batch create are documented in pm_create_tasks docstring
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-31
points: 1
priority: must
status: backlog
tags:
- tier-1
- dependencies
- documentation
title: Document blocked status vs dependency blocking distinction
updated: '2026-03-06'
---

As a user, I want clear documentation distinguishing user-set "blocked" status from automatic dependency-based blocking so that I understand why tasks appear in different board sections. Currently "blocked" is an explicit status users set, while incomplete dependencies cause tasks to appear in "not_ready" — these are independent concepts that can confuse users.