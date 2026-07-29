---
acceptance_criteria:
- pm_audit returns a digest identifying the current project state
- pm_audit accepts a since parameter and answers cheaply when nothing changed
- The health check still detects new ERROR-level findings promptly
- pm-orchestrate passes the previous digest on its periodic health check
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-2
id: US-PM-11
points: 3
priority: should
status: backlog
tags:
- context-cost
- orchestrator
- audit
title: Change detection for pm_audit
updated: '2026-07-29'
---

As an orchestrator polling project health, I want an unchanged audit to answer cheaply, so that my health check is not a byte-for-byte repeat.

pm-orchestrate/SKILL.md calls pm_audit in Phase 1 step 2, and again as a health check every 3 accepted tasks (step 21), stopping the run on new ERROR-level findings.

The studies read the resulting repetition as waste: Study D found 92 of 139 pm_audit calls were byte-identical repeats within a single session; Study C found pm_audit called with empty args up to 6 times in one session, and counted 298 identical repeat calls overall.

Study D's recommendation — cache pm_audit per session — is wrong, because it would disable the health check. The poll is the correct design. What is missing is a cheap way to answer "nothing changed".

Proposed: return a digest or generation counter, and accept a since parameter so an unchanged project answers in a few bytes instead of 162-10,440 chars. This keeps the safety property while removing the cost, and it composes with US-PM-5 which adds a new audit check.