---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-26-4
id: US-PM-26-5
points: 1
status: done
story_id: US-PM-26
tags: []
title: Make session-start pm_context optional outside the orchestrator
updated: '2026-09-05'
---

In agent_pm.md.j2 and skill_pm.md.j2 replace the session-start pm_context requirement with a pointer: 'pm_context(max_doc_chars=2000, limit=5) gives a bounded project brief when you need one'. Leave skill_pm_orchestrate.md.j2's once-per-run fetch untouched. Update tests that pin the old requirement.