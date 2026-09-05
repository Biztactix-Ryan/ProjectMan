---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-25-5
id: US-PM-25-6
points: 3
status: done
story_id: US-PM-25
tags: []
title: Rewrite skill_pm_orchestrate.md.j2 as instruction only under 9000 characters
updated: '2026-09-05'
---

Using the section list from the previous task, rewrite the template so only instructions remain: pre-flight checklist, the worker prompt template, the dispatch loop, verdict recording, resume, and the stop conditions. Link docs/reference/orchestrate-design.md exactly once near the top. Rendered output (run `projectman refresh-skills` into a tmp dir or render with jinja in a test) must be <= 9000 chars. Keep every tool call name and argument that appears today; the behaviour must not change, only the prose. Never run refresh-skills against ~/.claude in this task.