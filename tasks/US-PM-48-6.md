---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-48-5
id: US-PM-48-6
points: 3
status: done
story_id: US-PM-48
tags: []
title: Rewrite Validation steps 16-19 to spawn the validator and map its verdict
updated: '2026-09-09'
---

In skill_pm_orchestrate.md.j2 replace steps 16-18 (status check, diff check, DoD check run by the orchestrator) with: spawn the validator `Agent` (subagent_type general-purpose, executor model tier, foreground, no worktree) using the new prompt block; keep the orchestrator's own status check as a single projected `pm_get(task_id, fields="status,assignee")`. Step 19 maps the verdict field straight onto pm_accept / pm_retry / pm_park / pm_review with the verdict object (minus `verdict` and `note`) passed as `evidence` and `note` as the one-line note. A malformed or missing verdict counts as one validation failure: re-run the validator once, then park with note "validator returned no verdict". Keep the rendered template under 9000 characters; trim the rationale sentences the design doc already carries if needed.