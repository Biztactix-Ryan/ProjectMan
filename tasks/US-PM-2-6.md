---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-2-4
id: US-PM-2-6
points: 1
status: done
story_id: US-PM-2
tags: []
title: 'Test: expected negatives are not errors'
updated: '2026-07-29'
---

Verify acceptance criterion 3. Assert pm_grab on a not-ready task and pm_done_next with no next task both return success with a structured reason rather than is_error.