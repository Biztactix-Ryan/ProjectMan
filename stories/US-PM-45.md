---
acceptance_criteria:
- No web route accepts a prefix or project parameter and web/resolve.py is deleted
- The indexer builds INDEX.md for the one store and has no hub README or badge code
- pm_audit has no hub documentation check and run_audit takes no project_dir or known_epic_ids
  and the digest reads one config.yaml
- The web and indexer and audit suites pass
created: '2026-09-08'
depends_on: []
epic_id: EPIC-PM-6
id: US-PM-45
points: 3
priority: must
status: done
tags:
- subtraction
- hub
- web
title: Web, indexer and audit have no hub branch
updated: '2026-09-08'
---

As a user of the web UI and the audit, I want the web layer, the index builder and pm_audit to know only one store so that no route takes a prefix or project parameter and no check or digest reads a hub configuration.

State on 2026-09-08: src/projectman/web/resolve.py (117 lines, added in Sprint 12) resolves a store from an ID prefix or a ?prefix= query; web/routes/api.py has 27 prefix sites and a per-subproject store cache; indexer.py builds a hub README with per-project stats and workflow badges (_build_hub_readme, _workflow_badges via hub.stores.subproject_path and hub.rollup.rollup) when store.config.hub is set; audit.py Check 11 emits missing-hub-documentation, unfilled-hub-documentation and stale-hub-documentation, compute_state_digest mixes the hub's config.yaml into a subproject digest, and run_audit takes project_dir and known_epic_ids for the hub case.

Tests to delete with the code: tests/web/test_prefix_routing.py, tests/web/test_store_resolver.py, and the hub cases in tests/test_web_store_caching.py and tests/test_indexer.py. Keep the single-store cases those files also carry.