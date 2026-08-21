---
acceptance_criteria:
- The worker prompt template includes project architecture context
- The scoping and estimation workflows consult pm_estimate before writing points
- Skill files name the step at which each guidance tool is called
- Usage of both tools is visible in the next telemetry baseline
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-2
id: US-PM-13
points: 2
priority: should
status: done
tags:
- orchestrator
- skills
- quality
- docs
title: Wire pm_context and pm_estimate into the workflows that need them
updated: '2026-08-21'
---

As a worker agent, I want the project's architecture and estimation guidance available at the moment I need it, so that I am not implementing or sizing blind.

Two tools that sound directly useful have near-zero usage, and both studies that noticed flagged it as worth investigating rather than assuming the tools are unwanted.

pm_estimate — 1, 2, 0 and 0 calls across the four studies. Its docstring says it "returns content + calibration guidelines." Meanwhile 400+ points values were written across the corpora (Study A 180 points-only calls, Study B 214) with the calibration tool never consulted. Estimates are being invented, not calibrated.

pm_context — 8, 1, 1 and 0 calls. Its docstring says it is "for an agent starting work" and returns hub vision, architecture and project docs. But pm-orchestrate's Worker Prompt Template hand-inlines only story context and the DoD checklist, so workers implement code having never seen the project's architecture or security docs. That is a work-quality gap, not a token gap.

The diagnosis: pm_scope (guidance for decomposition) gets 28-40 calls while pm_estimate (guidance for sizing) gets 1-2, despite being the same shape. The difference is that scoping is a named discrete activity the model recognises, whereas estimation happens implicitly inside it. Guidance tools only get called when they map to a step someone explicitly takes — so the fix is to put them in the skill files, not to reword their docstrings.

Mostly a documentation change. Cheapest quality win in the epic.