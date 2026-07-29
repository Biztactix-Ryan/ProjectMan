---
acceptance_criteria:
- Oversized notes are truncated server-side with a visible marker rather than rejected
- Response carries a note_truncated flag so the caller knows
- The status and outcome portion of the write always lands regardless of note length
- Regression test covers a note at the limit and well over it
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-1
points: 2
priority: must
status: done
tags:
- reliability
- quick-win
title: Stop rejecting oversized run-log notes
updated: '2026-07-29'
---

As an agent completing a task, I want my run-log note accepted even when it exceeds the size limit, so that a long note never costs me the status write that came with it.

`store.py:985` raises `ValueError("Run-log note must be 1024 characters or fewer")`. Measured impact:
- Study A: 290 failures = 9.5% of ALL ProjectMan traffic; 1 in 4 pm_done_next calls
- Study B: 136 failures, 100% retried within 3 calls

The cap sits inside the natural distribution of what the model writes. Study B measured p90 = 1,067 chars against a 1,024 cap; Study A measured median 925 / p95 1,349. So the rejection rate is a function of how verbose notes happen to be and will worsen as run logs get richer.

Atomicity hazard: validation happens after `status` is staged into kwargs, so a "mark done" and its note fail as a unit. Nothing was lost in these corpora only because the model read the error text and retried. A non-interactive caller that checks `is_error` would silently drop the completion.

Recovery cost measured: ~426 wasted round trips plus ~426 regenerated notes across the two studies. Median retry note was 895 chars, so the surplus detail was discarded rather than stored.

Note: US-PM-9 (structured evidence) removes the underlying reason notes are long. This story is the immediate unblock.