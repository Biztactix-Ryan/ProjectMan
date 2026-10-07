---
acceptance_criteria:
- A band above the prompt shows active sprint progress, the in-progress task and the
  NEXT.md note when one exists
- The band updates after pm MCP tool calls that change status
- The band hides itself when the directory has no ProjectMan store
- Where the band draws, the SessionStart hook's injected status is dropped or reduced,
  and the context saved is recorded
- Where nothing draws, the SessionStart status injection keeps working as today
created: '2026-10-07'
depends_on:
- US-PM-60
epic_id: EPIC-PM-8
id: US-PM-62
points: 3
priority: could
status: backlog
tags:
- plugin
- mod
- ui
title: 'Mod: sprint band above the prompt'
updated: '2026-10-07'
---

As a user starting or resuming a session, I want a band above the prompt showing the active sprint's progress, the task in flight and the NEXT.md note, so that I see where things stand without the SessionStart hook injecting status text into the model's context.