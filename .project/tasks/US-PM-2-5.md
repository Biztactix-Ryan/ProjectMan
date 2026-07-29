---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-2-3
id: US-PM-2-5
points: 1
status: done
story_id: US-PM-2
tags: []
title: 'Test: every known failure class sets is_error'
updated: '2026-07-29'
---

Verify acceptance criteria 1, 2 and 4. Parameterised test driving each failure class identified in the inventory; assert is_error is set and no response body begins with the error prefix.