---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-1-2
points: 1
status: done
story_id: US-PM-1
tags: []
title: Truncate oversized run-log notes instead of raising
updated: '2026-07-29'
---

Replace the ValueError at store.py:985 with server-side truncation to the limit plus a visible marker such as ...[truncated N chars]. The status and outcome portion of the write must land regardless of note length.

Decide between truncating at 1024 and raising the cap to 4096 first — Study B p99 is 1,532 and max 2,155, so 4096 would eliminate nearly all truncation while staying bounded.