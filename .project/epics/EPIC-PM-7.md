---
created: '2026-09-09'
id: EPIC-PM-7
points: null
priority: should
status: active
tags:
- orchestrator
- cost
- context
target_date: null
title: Orchestrator context and cost slimming
updated: '2026-09-09'
---

Bring the per-task context cost of a /pm-orchestrate run down and keep the orchestrator productive while workers run, so an 8-hour sprint run stays well under 300k tokens and total spend stops growing quadratically with dispatches.

Baseline measured 2026-09-09 from Claude Code session transcripts (usage per API call, deduped by message id):
- Context growth per accepted task: ProjectMan 9.4k (Fable 5, Aug 21), 8.0k and 7.0k (Fable 5.1, Sep 5 and Sep 8). Kura 16.5k, 16.7k, 27.8k (Fable 5.1), which produced the 535k and 603k sessions.
- Thinking per API call is flat (~1.1k tokens) across models; calls per dispatch rose from 4 to ~7 with the validation steps. Retained thinking is ~20-25% of growth; visible tool traffic (validation Bash output, pre-flight reads, worker prompts and reports) is the rest.
- Nothing ever leaves the context: peak == final in every session, no compaction, no drop at task notifications. Cost per call grows linearly and total cost roughly quadratically with dispatches.
- Cache misses happen exactly when a worker wait exceeds the 1-hour cache TTL (3 per long Kura run, each rewriting 200-450k tokens; ~5% of input cost). Worker waits: ProjectMan p50 8-11 min, max 25; Kura p50 21-36 min, p90 60-105, max 165.
- Points predict duration: ProjectMan 1/2/3-pt tasks run 2/16/21 min median; Kura 12/46/75 min median with 2-pt p90 at 156 min.

Success criteria:
1. Orchestrator context growth per accepted task under 5k tokens on a ProjectMan sprint run, measured the same way.
2. No full cache misses attributable to worker waits, because tasks that would run past an hour are split at planning time.
3. Two independent tasks can be in flight at once when the sprint's dependency graph allows it, with worker isolation that keeps their edits separable.

Scope: pm-orchestrate skill template and its design doc, pm-plan skill, projection/brief options on the pre-flight tools, a per-project duration-per-point signal from activity.jsonl, and an ADR revising the stage-only model where isolation requires it. Out of scope: anything changing the cache TTL or the harness.