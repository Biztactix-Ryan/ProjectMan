---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-45-5
points: 1
status: done
story_id: US-PM-45
tags: []
title: Remove prefix routing and the per-subproject store cache from the web layer
updated: '2026-09-08'
---

Delete src/projectman/web/resolve.py. In src/projectman/web/routes/api.py and pages.py resolve the one store from the app's root for every route; remove ?prefix= handling and the per-subproject store cache (keep the single-store cache tests in tests/test_web_store_caching.py). Delete tests/web/test_prefix_routing.py and tests/web/test_store_resolver.py. Scrub 'prefix' and 'hub' from src/projectman/web/README.md. Run tests/web and tests/test_web_store_caching.py.