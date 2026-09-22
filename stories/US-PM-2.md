---
acceptance_criteria:
- Tool failures raise a real MCP error rather than returning an error string body
- is_error is set on every failure path
- Expected-negative results are distinguished from failures so pm_grab on a not-ready
  task is not an error
- No tool returns a body beginning with the error prefix
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-2
points: 5
priority: must
status: done
tags:
- reliability
- observability
- blocker
title: Surface soft errors as genuine MCP errors
updated: '2026-07-29'
---

As a caller of the ProjectMan MCP server, I want failures to be reported as errors, so that I can detect them without string-matching response bodies.

Tools catch exceptions and `return f"error: {e}"`, producing an HTTP 200 result whose body begins with `error:`. `is_error` is never set, so these are invisible to any transport-level metric.

Measured: Study B found 155 such calls (4.7%) against 47 hard errors (1.4%) — a true failure rate of 6.2%. Study A found 313 soft (10.3%) against 68 hard (2.2%) — 12.5% total.

Proof of how invisible this is: the two studies that did NOT scan response bodies (Study D, Study C) reported 1.8% and 1.1% failure rates on corpora of 2,752 and 5,134 calls. The methodological split is perfectly clean — every study that scanned bodies found 6-12%; every study that trusted is_error found ~1%. Study C's published "1.1% errored" figure understates reality by roughly an order of magnitude.

Observed soft-error messages: run-log note cap (135 on Study B alone); "task is not ready to grab" (12-14); "No .project/config.yaml found in any parent directory" on pm_status/pm_docs/pm_repair.

This is the measurement prerequisite for the entire plan. Until it lands neither the orchestrator nor any future study can tell a working call from a failed one.