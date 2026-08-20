---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-7-8
id: US-PM-7-9
points: 1
status: done
story_id: US-PM-7
tags: []
title: Rewrite the SKILL.md release instructions
updated: '2026-08-20'
---

pm-orchestrate/SKILL.md instructs pm_update(<id>, status=todo, assignee="") in two places: step 13 (max-budget release of a pre-claimed task) and the stop-conditions block. Both must use the new verb.

This is the immediate mitigation and can ship ahead of the store work — the skill file is currently the highest-volume generator of the malformed-JSON error class.