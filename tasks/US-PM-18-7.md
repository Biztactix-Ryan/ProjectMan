---
assignee: claude
created: '2026-08-20'
depends_on:
- US-PM-18-6
id: US-PM-18-7
points: 2
status: done
story_id: US-PM-18
tags: []
title: Add regression tests for comma-bearing acceptance criteria
updated: '2026-08-20'
---

Add tests proving a criterion containing commas (e.g. "Given a user, when they log in, then the dashboard loads") is stored as exactly one criterion via pm_create_story and via pm_update, and that pm_update criteria edits still reconcile auto-generated test tasks (extend tests/test_criteria_task_reconciliation.py or add a sibling test module). Include the bare-string-as-single-criterion case if Union[str, list[str]] was chosen.