---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on: []
id: US-PM-25-5
points: 2
status: done
story_id: US-PM-25
tags: []
title: Move the rationale and resume-protocol essay to docs/reference/orchestrate-design.md
updated: '2026-09-05'
---

Read src/projectman/templates/skill_pm_orchestrate.md.j2 (31.7KB). Separate every paragraph into 'instruction' (an agent must do X) and 'rationale' (why X, anecdotes, sizes, history). Write the rationale into a new docs/reference/orchestrate-design.md with headings: Stage-only model, Pre-flight, Dispatch and worker prompt, Verdicts and evidence, Resume protocol, Known failure modes (include the 2026-08-21 git-checkout incident and the Sprint 6 stray-story incident as the reasons behind the worker rules). Do not edit the template in this task; just produce the doc and list, in the run log, which template sections it absorbs.