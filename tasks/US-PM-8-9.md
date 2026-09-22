---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-8-7
id: US-PM-8-9
points: 2
status: done
story_id: US-PM-8
tags: []
title: Rewrite pm-orchestrate to use the verdict verbs
updated: '2026-08-21'
---

Replace the pm_update and pm_done_next calls in step 19 with the new verbs. This is where the adoption problem actually gets fixed — 512 pm_grab-then-pm_update(done) pairs still beat 387 pm_done_next calls despite the docstring at server.py:1343 steering toward it, so the fix has to be in the skill's instructions rather than in tool documentation.