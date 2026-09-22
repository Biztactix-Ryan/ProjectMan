---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-25-6
id: US-PM-26-4
points: 1
status: done
story_id: US-PM-26
tags: []
title: Make pm_estimate calibration optional in the interactive skills
updated: '2026-09-05'
---

In skill_pm.md.j2 (Estimation section, lines ~43-66), skill_pm_plan.md.j2 and skill_pm_do.md.j2: change 'run pm_estimate first' from a requirement to a one-line suggestion ('pm_estimate(<id>) returns the calibration bands and this project's averages if you want them'). The orchestrate template keeps its rule; do not touch it. Update any test in tests/ that asserts the interactive skills mandate pm_estimate.