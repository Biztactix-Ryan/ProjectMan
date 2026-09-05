---
acceptance_criteria:
- Interactive skill templates no longer require pm_estimate before writing points
- Interactive skill and agent templates no longer require pm_context at session start
- The orchestrate skill still mandates the once-per-run bounded pm_context and refuses
  unestimated sprint content by directing to /pm-plan
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-26
points: 2
priority: should
status: done
tags:
- skills
- subtraction
title: pm_estimate and session-start pm_context are mandatory only under the orchestrator
updated: '2026-09-05'
---

As a developer using /pm interactively, I want to set points or start a session without a ritual calibration call so that a one-line update stays a one-line update.

Today src/projectman/templates/skill_pm.md.j2 requires `pm_estimate(<id>)` before any `points=` write and agent_pm.md.j2 requires `pm_context` at session start. The audit found both were adopted for the orchestrator's benefit (bounded context, calibrated worker estimates) and then applied everywhere. Interactively they cost a round trip and rarely change the answer.

Change: in skill_pm, skill_pm_plan, skill_pm_do and agent_pm the calibration and context-fetch become "available when you want them" guidance with a one-line pointer; the orchestrate skill keeps its once-per-run bounded pm_context and its calibrate-before-estimate rule. Depends on the orchestrate rewrite landing first so the two templates are edited against the same wording.