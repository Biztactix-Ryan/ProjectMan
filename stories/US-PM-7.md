---
acceptance_criteria:
- Releasing a task is expressible without an empty-string or null sentinel
- Claiming uses compare-and-swap so two concurrent workers cannot both win
- Clearing depends_on and tags has an explicit affordance
- pm-orchestrate SKILL.md no longer instructs the unspellable update
- Concurrent claim attempts are covered by a test
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-2
id: US-PM-7
points: 8
priority: must
status: done
tags:
- workflow
- orchestrator
- concurrency
- blocker
title: Atomic task claim and release primitive
updated: '2026-08-20'
---

As an orchestrator, I want claiming and releasing a task to be a single atomic operation with a name, so that release is spellable and parallel workers become possible.

This is the highest-leverage item in the plan: one store-level change fixes an entire error class AND removes a stated architectural blocker.

Problem 1 — release is unspellable. pm-orchestrate/SKILL.md instructs the orchestrator, in two places (step 13 and the stop-conditions block), to run:
    pm_update(<id>, status="todo", assignee="")
The model cannot reliably emit this. Every parameter is Optional[str] = None, so `null` already means "leave unchanged"; the model reaches for null, finds it taken, and emits a bare key instead: {"id": ..., "status": "todo", "assignee": }. Measured malformed calls: Study D 48 of 49 total errors, Study C 31 of 45, Study B 27, Study A 62. Study C's payloads carry the note text "Released by orchestrator..." confirming this is the orchestrator's hot path.

Critically, this was already "fixed" once. Commit 2261a0d (2026-07-04, v0.8.14) added pm_update(assignee="") clears the assignment plus one docstring line at argument 5 of 14. Study D's failures run 2026-07-24 to 2026-07-28 — three weeks after. A docstring sentinel cannot beat the null prior. This is a schema-shaped problem and needs a schema-shaped fix.

Problem 2 — no atomic claim. SKILL.md states the limitation outright: "No parallel workers — sequential until the store supports atomic claiming." The same missing primitive causes both.

Fix: a real claim/release pair with compare-and-swap semantics. A boolean or a dedicated verb has no malformed form. Also give depends_on and tags an explicit clear affordance — Study C measured 17 malformed depends_on clears with no documented sentinel at all.