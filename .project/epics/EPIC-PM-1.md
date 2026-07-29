---
created: '2026-07-29'
id: EPIC-PM-1
points: null
priority: must
status: draft
tags:
- reliability
- mcp
- agent-facing
target_date: null
title: Correctness & Observability
updated: '2026-07-29'
---

Make ProjectMan's failures visible and stop losing writes.

Evidence base: four independent tool-usage studies (Study/ directory) covering ~14,200 MCP calls across 4 machines, ~1,500 sessions and ~13 consumer repos, on versions 0.8.9 and 0.8.15.

The headline result is that ProjectMan's real failure rate is 6-12%, not the ~1% that transport-level metrics report. Failures are raised as ValueError, returned as HTTP 200 with an `error:` string body, and are therefore invisible to any caller checking `is_error` — including ProjectMan's own orchestrator. Two of the four studies undercounted errors by ~10x for exactly this reason.

Success criteria:
- No write path rejects a caller's payload where truncation or coercion would do
- Every failure is visible to the caller as a genuine MCP error
- The measured failure rate after these fixes is verifiable by a repeatable in-repo script

These are small, contained edits and account for most of the measured loss. Do this epic before the workflow redesign — until soft errors surface, nothing downstream can be measured.