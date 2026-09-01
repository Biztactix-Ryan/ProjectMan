---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-14-5
id: US-PM-14-6
points: 2
status: done
story_id: US-PM-14
tags: []
title: Replace the Phase 1 ownership guess with an activity query
updated: '2026-08-22'
---

SKILL.md Phase 1 step 3 currently guesses whether in-progress tasks belong to a previous orchestrator run and asks the human when unsure. pm_activity with actor and event_type filters answers this directly.