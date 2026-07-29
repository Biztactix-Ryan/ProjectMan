---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-2-2
id: US-PM-2-4
points: 2
status: done
story_id: US-PM-2
tags: []
title: Keep expected-negative results as successful responses
updated: '2026-07-29'
---

pm_grab on a task that is not ready is a legitimate answer, not a failure — the caller asked a question and got a valid negative. Return these as success with a structured reason field so callers can branch without string-matching. Same treatment for pm_done_next returning next: null, which Study B measured at 89 of 413 calls with a useful next_info hint that demonstrably works.