---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-44-5
points: 3
status: done
story_id: US-PM-44
tags: []
title: Drop the prefix parameter and the store-for-prefix resolvers from server.py
updated: '2026-09-08'
---

Remove prefix: Optional[str] = None from all 24 tools in src/projectman/server.py and delete _store_for_prefix and _project_dir_for_prefix, replacing every call with the single store (the existing per-process _store_cache keyed by root). Keep the coded not_found for an ID whose prefix is not in this store. Delete the hub_stores import. Update docstrings that mention 'hub mode only' or 'prefix'. Run tests/test_server.py, tests/test_server_routing.py, tests/test_expected_negatives.py and tests/test_tool_gating.py; hub-only cases in them are deleted by the next task.