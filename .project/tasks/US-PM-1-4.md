---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-1-2
id: US-PM-1-4
points: 1
status: done
story_id: US-PM-1
tags: []
title: 'Test: oversized note truncates and the status write still lands'
updated: '2026-07-29'
---

Verify acceptance criteria 1 and 3. Submit a note well over the limit alongside a status transition; assert the item reaches the new status, the run-log entry exists, the note is truncated with a marker, and no error is raised.