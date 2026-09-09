---
acceptance_criteria:
- The orchestrate skill template dispatches a validator subagent after each worker
  and never runs the tests or md5 comparison in its own context
- The validator prompt template asks for a single bounded JSON verdict with files,
  tests, dod_met, dod_unmet and a note under 200 characters
- The orchestrator maps the validator verdict onto pm_accept, pm_retry, pm_park or
  pm_review with the verdict object passed as evidence
- orchestrate-design.md explains the validator subagent and why its report is bounded,
  and the skill template stays under 9000 characters
created: '2026-09-09'
depends_on: []
epic_id: EPIC-PM-7
id: US-PM-48
points: 8
priority: must
status: done
tags:
- orchestrator
- context
title: Orchestrator delegates validation to a validator subagent
updated: '2026-09-09'
---

As the sprint orchestrator, I want the status, diff and DoD checks (skill steps 16-18) run by a validator subagent that returns a bounded verdict, so that the test output, md5 listings and diff stats never enter the orchestrator's own context and per-task growth drops from 7-28k tokens to a few thousand.

Design: after the worker returns, the orchestrator spawns a validator Agent (same executor tier, foreground) with the task id, run id, the DoD list, the step 14 snapshot path and the pre-dispatch md5 list. The validator runs `git status --short`, `git diff --stat`, the md5 comparison and the tests the DoD names, and reports back one JSON object: {verdict: accept|retry|park|review, files: [...], tests: [{command, passed, summary}], dod_met: [...], dod_unmet: [...], note: "<=200 chars"}, capped at about 1500 characters. The orchestrator maps that straight onto pm_accept / pm_retry / pm_park / pm_review with the object as evidence. Validation stays independent of the worker, which is what the design doc's trust-but-verify rule protects; it just runs in a context that is discarded.

Touches: src/projectman/templates/skill_pm_orchestrate.md.j2 (keep under 9000 chars), docs/reference/orchestrate-design.md (new section on the validator and why its report is bounded), the skill-content tests, and the rendered .claude/ copies regenerated via scratchpad + cp.