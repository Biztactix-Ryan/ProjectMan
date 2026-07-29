---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-1-3
id: US-PM-1-5
points: 1
status: todo
story_id: US-PM-1
tags: []
title: 'Test: note_truncated flag and boundary lengths'
updated: '2026-07-30'
---

Verify acceptance criteria 2 and 4. Cover a note exactly at the limit (no truncation, flag false), one char over (truncated, flag true), and a very large note. Assert the flag is present and correct in each case.