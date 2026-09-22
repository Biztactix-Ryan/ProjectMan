---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-49-7
points: 2
status: done
story_id: US-PM-49
tags: []
title: Slim the worker prompt and cap the worker report
updated: '2026-09-09'
---

In the worker prompt template of skill_pm_orchestrate.md.j2 remove the `Project context: <architecture excerpt>` line; the worker calls pm_context itself when it needs it (pm_grab already returns the task context). Replace `Report back: files changed; test commands with pass/fail; DoD met and unmet.` with a fixed shape: files changed (paths only), tests run as `command -> pass|fail (n passed)`, DoD met, DoD unmet, blockers, in that order and under 1500 characters total, no code or logs. Mirror the same report shape in the reporting section of skill_pm_do.md.j2 so a worker that reads /pm-do gets the same instruction.