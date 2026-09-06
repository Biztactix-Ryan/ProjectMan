---
acceptance_criteria:
- No route or dependency in src/projectman/web/routes/api.py declares a project query
  parameter
- In a hub an ID route such as GET /api/items/US-API-3 resolves the store from the
  ID prefix with no other argument and an unknown prefix returns 404 with a coded
  error
- ID-less routes such as status board search and create accept an optional prefix
  query parameter and a hub create without one returns 422 with the invalid code
- GET /api/status in a hub still returns the subprojects rows and every single-project
  response is byte-for-byte unchanged
- docs/reference and src/projectman/web/README.md no longer mention ?project= and
  ADR-003 records that the web layer now routes by prefix
created: '2026-09-06'
depends_on: []
epic_id: null
id: US-PM-39
points: 5
priority: should
status: backlog
tags:
- web
- hub
- subtraction
title: The web API routes by ID prefix and drops the ?project= query parameter
updated: '2026-09-06'
---

As a hub operator using the web dashboard, I want the HTTP API to find a subproject's store from an ID's prefix the way every MCP tool has since US-PM-34, so that the last surviving project argument leaves the surface and the open consequence recorded in ADR-003 closes. Today get_project_dir and get_store in src/projectman/web/routes/api.py are FastAPI dependencies that take `?project=` and look the name up in the store map; all 26 routes inherit it. The MCP server already has the resolver that parses a prefix out of an ID and picks the store (US-PM-34-6, `_store_for_id` in server.py) and the ID-less verbs take an optional `prefix`. Mirror that in the web layer: ID-taking routes (get, update, archive, epic rollup, run log) resolve the store from the ID; ID-less routes (status, board, search, list, create) take an optional `prefix` and, in a hub, a create without one is a 422 with the `invalid` code through web/errors.py. GET /api/status keeps its `subprojects` rows. Single-project mode is unchanged. No static asset or template sends `project=` today, so the front end needs no change beyond any request that names a prefix. Finish by removing every `?project=` mention from docs/reference and src/projectman/web/README.md and appending the closure to ADR-003's consequences.