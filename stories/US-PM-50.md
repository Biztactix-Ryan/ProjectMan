---
acceptance_criteria:
- A store function returns per-points p50, p90 and count of grab-to-done minutes computed
  from orchestrated status transitions in activity.jsonl
- pm_estimate and pm_scope include duration_history for the project alongside estimation_guidance
- The sprint view lists tasks whose points band has p90 above orchestrate.max_task_minutes
  (default 60) under long_task_risk
- The pm-plan skill runs the long-task check before activating a sprint and offers
  to re-scope flagged tasks
- pm_audit warns when an active sprint contains a task flagged as long_task_risk
created: '2026-09-09'
depends_on: []
epic_id: EPIC-PM-7
id: US-PM-50
points: 5
priority: should
status: done
tags:
- planning
- cost
title: pm-plan flags tasks likely to run past an hour and asks to split them
updated: '2026-09-09'
---

As a sprint planner, I want ProjectMan to tell me which tasks are likely to run longer than the one-hour cache window on this project, so that I split them before the sprint instead of paying a full prefix rewrite each time a worker overruns.

The signal already exists in activity.jsonl: grab-to-done durations for tasks worked under an orch- run, keyed by points. Measured 2026-09-09: ProjectMan 1/2/3-point tasks run 2/16/21 minutes median with a 44 minute max; Kura 12/46/75 minutes median with 2-point p90 at 156 minutes and 5-point at 133. Every cache miss in the long Kura runs sat right after a worker wait over 60 minutes.

Changes: (1) a store function that computes per-points duration percentiles (p50, p90, n) from orchestrated status transitions in activity.jsonl; (2) pm_estimate and pm_scope return it as duration_history alongside estimation_guidance; (3) pm_get_sprint (or a new pm_plan_check) lists tasks whose points band has p90 over a configurable threshold (default 60 minutes, config key orchestrate.max_task_minutes) as long_task_risk; (4) the pm-plan skill runs that check before activating and offers to re-scope flagged tasks into smaller ones; (5) pm_audit raises a warning for an active sprint containing flagged tasks.