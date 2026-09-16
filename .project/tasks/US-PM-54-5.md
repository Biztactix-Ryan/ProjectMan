---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-17'
depends_on: []
id: US-PM-54-5
points: 2
status: done
story_id: US-PM-54
tags: []
title: Add the heartbeat to skill_pm_orchestrate.md.j2 and regenerate the rendered
  skill
updated: '2026-09-17'
---

Phase 0 gains a Heartbeat step: one session-only CronCreate every 30 minutes ("13,43 * * * *") whose prompt names the run id, tells the orchestrator to answer in a few words with no tools while a worker is out, and to CronDelete the job when no run is in flight. Phase 4 and the stop conditions delete it. Trim elsewhere so the rendered skill stays under the size cap; regenerate .claude/skills/pm-orchestrate/SKILL.md from the template.