---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-11-5
id: US-PM-11-6
points: 1
status: done
story_id: US-PM-11
tags: []
title: Accept a since parameter and short-circuit when unchanged
updated: '2026-08-21'
---

When the caller passes a digest matching current state, answer in a few bytes instead of 162-10,440 chars. Must still detect new ERROR-level findings promptly — the point is to keep the poll, not weaken it.