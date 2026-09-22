---
acceptance_criteria:
- Script walks Claude Code transcripts and joins tool calls to results by tool_use_id
- Reports hard errors and soft errors and malformed inputs separately
- Reports per-tool call counts and response bytes and consecutive-run lengths
- Match rate is asserted and the run fails loudly if it drops below 99 percent
- A baseline is captured and committed before other fixes land
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-6
points: 3
priority: should
status: done
tags:
- observability
- measurement
- tooling
title: Repeatable usage-telemetry analysis script
updated: '2026-07-29'
---

As a maintainer, I want the tool-usage study to be a repo artifact, so that I can verify these fixes actually moved the numbers instead of assuming they did.

All four studies in the internal usage studies were written as throwaway scratchpad scripts, and two of the four got the methodology wrong in the same way — they counted only `is_error` and so reported ~1% failure rates on corpora where the real rate was 6-12%. The correct method is documented across the four appendices but exists nowhere in the repo.

The three non-obvious points that materially change the numbers:
1. Soft errors are not is_error — match an error prefix inside the response body as well
2. Malformed calls surface as an `__unparsedToolInput` key in the input dict rather than as a parse failure — count that key explicitly
3. Result records do not contain the string "projectman", so tool_result blocks cannot be pre-filtered by it; do a two-pass scan and join on tool_use_id, then verify the match rate is ~100% before trusting any downstream number

This story is what makes the rest of the plan falsifiable. Ship it early and capture a baseline before the other fixes land.