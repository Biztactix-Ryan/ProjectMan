---
acceptance_criteria:
- Every tool taking a typed ID also accepts the generic id parameter
- Tools taking id also accept the typed alias where one exists
- Passing both a typed ID and id with conflicting values is a clear error
- Test covers each aliased tool with both spellings
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-3
points: 3
priority: must
status: done
tags:
- reliability
- quick-win
- ergonomics
title: Accept id and task_id as aliases on every tool
updated: '2026-07-29'
---

As an agent calling ProjectMan, I want the ID parameter to have one name, so that I stop guessing which tool wants which spelling.

Two conventions coexist across the API:
- `id`: pm_get, pm_update, pm_archive, pm_epic, pm_estimate, pm_scope, pm_run_log, pm_fix_malformed
- `task_id`: pm_grab, pm_done_next
- `sprint_id`: pm_get_sprint, pm_update_sprint

The model conflates them in both directions. Measured hard errors: Study A ~20, Study B 18, Study C 6+. Study B's argument-key census for pm_grab: task_id 459, include_story+task_id 33, `id` 15.

Observed failures include pm_grab({'id': 'US-CCO-173-1'}), pm_get_sprint({'id': 'SPRINT-RMM-1'}), pm_update({'task_id': 'US-HDC-10-3'}). Study C also found `task_id` as a stray key in 2 otherwise-valid pm_update calls.

This is a pure naming tax. All three studies that measured hard errors rank it as the cheapest complete elimination of an error class available — roughly one line per tool.