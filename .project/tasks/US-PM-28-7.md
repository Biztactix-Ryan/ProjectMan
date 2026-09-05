---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-28-5
id: US-PM-28-7
points: 1
status: done
story_id: US-PM-28
tags: []
title: The /pm-next skill template with refresh-skills wiring and docs
updated: '2026-09-05'
---

Add src/projectman/templates/skill_pm_next.md.j2 (~1KB, model on skill_pm_status.md.j2): no arguments -> call pm_next(), restate the note, propose the first concrete step and ask whether to start; text argument -> pm_next(text=...) and confirm; 'clear' -> pm_next(clear=true); after finishing the work a note describes, offer to clear it. Register the template wherever refresh-skills enumerates skills (cli.py refresh-skills and any skill-count test). Docs: a section in docs/user-guide and a row in docs/reference/skills.md and the MCP tool reference. Never run refresh-skills against ~/.claude in this task.