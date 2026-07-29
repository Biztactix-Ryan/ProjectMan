---
created: '2026-07-29'
id: EPIC-PM-2
points: null
priority: must
status: active
tags:
- workflow
- orchestrator
- mcp
- agent-facing
target_date: null
title: Workflow API for Agent Orchestration
updated: '2026-07-30'
---

Give the store a vocabulary for the orchestrator's state machine.

ProjectMan is currently a CRUD API that an agent is asked to drive as a workflow. Every flow defect in the studies traces to that gap: the model improvises workflow semantics with generic writes and gets it wrong at a measurable rate.

Evidence:
- 13% of `status=done` writes carry no note/outcome at all (163/1,266) — the run-log trail the schema exists to capture is silently missing
- The `outcome` vocabulary has collapsed to ~90% `success`
- Task release is unspellable: pm-orchestrate/SKILL.md instructs `pm_update(id, status="todo", assignee="")` and the model emits `{"assignee": }` instead — 31-48 malformed calls per corpus, carrying the note text "Released by orchestrator..."
- `pm_update` runs back-to-back up to 109 times; `pm_archive` up to 114, and 3 of those were denied mid-sweep by Claude Code's permission classifier
- pm_grab + pm_get are ~50% of all context returned, on ~25% of calls

Success criteria:
- The four orchestrator verdicts (Accept/Retry/Park/Review) each have a verb that cannot be spelled wrong
- Task claim/release is atomic, unblocking the parallel workers SKILL.md currently rules out
- Multi-item work is expressible as one reviewable call
- Guidance tools that already exist (pm_context, pm_estimate) are reachable from the workflows that need them

Depends on the Correctness epic only for measurement: until soft errors surface, improvements here cannot be validated.