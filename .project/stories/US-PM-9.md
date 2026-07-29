---
acceptance_criteria:
- Run-log entries accept structured evidence separate from the prose note
- Evidence records files changed and tests run with results and DoD items met
- Completions carrying no evidence are detectable via query or audit
- pm-orchestrate records evidence structurally rather than in the note
- Median note length drops well below the cap
created: '2026-07-29'
depends_on:
- US-PM-1
epic_id: EPIC-PM-2
id: US-PM-9
points: 5
priority: should
status: active
tags:
- workflow
- orchestrator
- run-log
title: Structured evidence on run-log entries
updated: '2026-07-30'
---

As an orchestrator validating a worker, I want to record evidence as structured fields, so that verification is queryable and notes stop hitting a prose cap.

This is the superset fix for the run-log note cap (US-PM-1). US-PM-1 raises or truncates the ceiling; this story removes the reason notes are long in the first place.

pm-orchestrate/SKILL.md steps 17-19 tell the orchestrator to record exactly three things: which files changed, which test commands ran and their results, and which DoD criteria were evidenced. That is structured data. It is currently flattened into a prose note, which is why note lengths cluster right at the 1024 ceiling — Study B measured p90 at 1,067 against the cap, Study A median 925 / p95 1,349.

Proposed: an evidence field alongside a short human-readable note, carrying files, tests with pass/fail, and dod_met. Benefits beyond the cap:
- "done with no evidence" becomes detectable rather than silent, addressing the 13% of completions with no run log at all
- evidence becomes queryable for audit and for the final orchestrator report
- the note returns to being a one-line human summary, which is what SKILL.md actually asks for

Sequence after US-PM-1 so the immediate bleeding is stopped first.