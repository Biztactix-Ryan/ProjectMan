---
assignee: null
created: '2026-07-29'
depends_on:
- US-PM-10-6
id: US-PM-10-8
points: null
status: todo
story_id: US-PM-10
tags: []
title: Use projection for the orchestrator validation read
updated: '2026-07-29'
---

SKILL.md step 16 should fetch only the fields it checks. Do not remove the read — it is the trust-but-verify step and is deliberate. Make it cheap instead.