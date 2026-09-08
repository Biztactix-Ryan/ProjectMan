---
acceptance_criteria:
- No tool in the MCP tool list has a prefix parameter
- server.py imports nothing from projectman.hub and has no code path conditioned on
  hub configuration
- pm_status and pm_epic and pm_burndown and pm_git_status and pm_malformed and pm_context
  answer for the single store with no subprojects or by_project or not_attached keys
- The hub server tests are deleted and the remaining suite passes
created: '2026-09-08'
depends_on: []
epic_id: EPIC-PM-6
id: US-PM-44
points: 5
priority: must
status: done
tags:
- subtraction
- hub
- server
title: The MCP server has one store and no prefix routing
updated: '2026-09-08'
---

As a user of the MCP tools, I want every tool to address the one store the server was started in so that no tool carries a prefix argument, no answer carries subproject or by_project or not_attached keys, and the server has no code path that depends on hub configuration.

State on 2026-09-08: server.py imports hub_stores from projectman.hub.stores; 24 tools take prefix: Optional[str] = None; _store_for_prefix and _project_dir_for_prefix resolve a store from an ID prefix; pm_status lists subprojects, pm_epic rolls up by_project with a not_attached list, pm_burndown and pm_git_status and pm_malformed and pm_reindex and pm_restore and pm_context and pm_audit each branch on load_config(root).hub. Single-project behaviour must not change: IDs keep their prefix (this repo has both PM and PRJ ids in one store), and an ID whose prefix is unknown still gets a coded not_found.

Hub server tests to delete with the code: tests/test_hub_routing.py, tests/test_hub_epics.py, tests/test_hub_unattached.py, tests/test_hub_commit_push_prefix.py, tests/test_hub_git_status.py, tests/test_hub_conflicts.py, tests/test_server_routing.py (hub cases only if it also covers single-store routing). Other tests that build a hub via tmp_hub are the package story's problem (US-PM-46); leave the fixture in place here.