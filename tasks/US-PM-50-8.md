---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-50-6
id: US-PM-50-8
points: 1
status: done
story_id: US-PM-50
tags: []
title: Return duration_history from pm_estimate and pm_scope
updated: '2026-09-09'
---

pm_estimate and pm_scope in server.py include a `duration_history` block next to estimation_guidance, with the per-points p50/p90/n and the threshold from config, and a `note` when fewer than three orchestrated tasks exist for the project. Extend tests/test_estimator.py.