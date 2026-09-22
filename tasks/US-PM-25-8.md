---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-25-6
id: US-PM-25-8
points: 1
status: done
story_id: US-PM-25
tags: []
title: Reconcile contradictory numbers across skill templates and code
updated: '2026-09-05'
---

Find and fix: task point range (template says 1-3 in one place and 1-5 in another — pick the one pm_estimate's guidance and skill_pm.md.j2 use); audit check count (13 vs 16 — count the checks in src/projectman/audit.py and use that number or drop the number); skill count (5 vs 7 — count templates named skill_*.md.j2); which call closes a story (pm_done_next vs pm_accept — read server.py and state the actual behaviour). Apply the same wording in skill_pm.md.j2, skill_pm_do.md.j2, skill_pm_plan.md.j2 and agent_pm.md.j2 wherever they mention these. List each contradiction and its resolution in the run log.