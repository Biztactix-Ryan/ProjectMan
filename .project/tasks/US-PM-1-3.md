---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-1-2
id: US-PM-1-3
points: 1
status: done
story_id: US-PM-1
tags: []
title: Return a note_truncated flag on the update response
updated: '2026-08-20'
---

The caller must be able to tell that truncation happened. Surface a note_truncated boolean (and ideally the original length) in the pm_update and pm_done_next responses so an automated caller can react without string-matching.