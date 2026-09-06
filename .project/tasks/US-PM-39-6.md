---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-39-6
points: 3
status: todo
story_id: US-PM-39
tags: []
title: 'Web-layer store resolver: prefix parsed from the ID or an optional prefix
  query picks the store'
updated: '2026-09-06'
---

Add a FastAPI dependency in src/projectman/web/routes/api.py (or a small web/resolve.py) that mirrors the server's US-PM-34 resolver: given an item ID, parse its prefix (EPIC-X-n, US-X-n, US-X-n-m via models.EPIC_ID/STORY_ID patterns) and look the prefix up in the hub store map (projectman.hub.stores); given no ID, accept an optional `prefix` query parameter. In single-project mode every prefix resolves to the one store as today. Reuse the existing _hub_store_cache. An unknown prefix raises the 404 coded error through web/errors.py; a hub create with no prefix raises 422 with code `invalid`. Do not touch routes yet; unit-test the dependency in isolation in tests/web/.