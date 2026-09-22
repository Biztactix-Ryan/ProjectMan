---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-10-6
points: 3
status: done
story_id: US-PM-10
tags: []
title: Add a fields parameter to pm_get and pm_grab
updated: '2026-08-21'
---

Projection selecting which keys are returned. Default unchanged when not supplied. The target case is the orchestrator's validation read at SKILL.md step 16, which needs only status and assignee but currently costs ~3,870 chars.