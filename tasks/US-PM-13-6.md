---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-13-6
points: 1
status: done
story_id: US-PM-13
tags: []
title: Call pm_estimate before writing points in the scoping workflows
updated: '2026-08-21'
---

400+ points values were written across the corpora with the calibration tool consulted 1-2 times total. Name the step explicitly in /pm scope and /pm-autoscope — the diagnosis is that guidance tools only get called when they map to a step someone takes, which is why pm_scope gets 28-40 calls and the identically-shaped pm_estimate gets 1-2.