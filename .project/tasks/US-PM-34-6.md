---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-31-6
id: US-PM-34-6
points: 3
status: todo
story_id: US-PM-34
tags: []
title: '_store_for_id resolver: prefix parsed from the ID picks the store'
updated: '2026-09-06'
---

In server.py add _store_for_id(item_id) that extracts the prefix with the models.py ID patterns (STORY_ID, TASK_ID, EPIC_ID, SPRINT_ID), returns the single store outside hub mode regardless of prefix, and in a hub looks the prefix up in hub_stores() from US-PM-31 (hub's own prefix maps to root/.project). Unknown prefix raises errors.NotFoundError with the known prefixes in the message; a malformed ID raises errors.InvalidError. Add a _stores_for_ids(ids) helper that groups a list of IDs by store preserving order. Unit tests for both in tests/test_server_routing.py.