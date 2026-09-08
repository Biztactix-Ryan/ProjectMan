---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PRJ-56-4
id: US-PRJ-56-5
points: 1
status: done
story_id: US-PRJ-56
tags: []
title: Update docs/user-guide/daily-workflow.md to drop standalone /pm scope references
updated: '2026-09-07'
---

Replace each standalone `/pm scope` (and any other /pm-<verb> shown as its own command) in docs/user-guide/daily-workflow.md with the routed form and a link to the new quick-reference table in skills.md. grep docs/ for `/pm scope` afterwards: zero hits outside the table.