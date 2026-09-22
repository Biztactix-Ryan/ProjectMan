---
acceptance_criteria:
- Archiving a task no longer sets its status to done
- Archived tasks are excluded from completion percentage and burndown
- Sprint velocity counts only genuinely completed points
- Existing archived-as-done tasks can be identified and corrected by a migration
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-16
points: 3
priority: must
status: done
tags:
- reliability
- metrics
- found-in-planning
title: Archiving a task should not mark it done
updated: '2026-07-29'
---

As someone reading project metrics, I want archived tasks excluded from completion, so that abandoned work is not counted as delivered.

Found while planning this epic — not present in any of the four studies.

store.py:1082-1088 dispatches by item type:
- epics   -> status archived
- stories -> status archived
- tasks   -> status DONE

TaskStatus has no archived member, so archiving a task was implemented as completing it. Archived tasks are then indistinguishable from genuinely finished ones.

Reproduced in this project: US-PM-1-1 and US-PM-2-1 were archived as obsolete auto-generated test tasks and immediately reported status done. pm_status now shows "done: 2" for a project where nothing has been completed.

Why this matters beyond cosmetics:
- completion percentage and burndown inflate with abandoned work
- sprint velocity is computed from completed points, and pm-orchestrate/SKILL.md step 24 proposes closing a sprint and reporting its completed points as velocity — so archived tasks corrupt the number future sprints are planned against
- /pm-cleanup exists specifically to archive finished work in bulk, and Study C measured 269 pm_archive calls with a single run of 114, so the blast radius is large

Fix: add an archived state for tasks, or an archived boolean orthogonal to status, and exclude archived items from completion and velocity math. Check pm_burndown and pm_status for the same assumption.