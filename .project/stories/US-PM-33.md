---
acceptance_criteria:
- docs/reference/agent.md no longer lists a mandatory pm_context call ahead of pm_status
  and matches the agent template
- POST create endpoints in the web API return 409 with the error code when the target
  ID already exists and 422 on an invalid ID
created: '2026-09-06'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-33
points: 2
priority: could
status: backlog
tags:
- docs
- web
- subtraction
title: 'Two worker-flagged leftovers: agent doc ordering and web create endpoints
  return 409 on ID collision'
updated: '2026-09-06'
---

Two small defects flagged by Sprint 8 and 9 workers and recorded in the next-session note, neither large enough for its own story.

1. docs/reference/agent.md lists "Fetch context via pm_context" as rule 1 and "Always start with pm_status" as rule 2. Since US-PM-26 pm_context is mandatory only under the orchestrator, so rule 1 contradicts both rule 2 and the skills. Reorder and reword so the doc says what the agent template says.

2. src/projectman/web/routes/api.py create_epic, create_story and create_task catch nothing but FileNotFoundError, so the ConflictError that US-PM-24 raises on an existing target surfaces as a 500. Map the coded errors from errors.py to HTTP status the same way the MCP layer does: conflict to 409, not_found to 404, invalid to 422.