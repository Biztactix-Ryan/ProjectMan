---
acceptance_criteria:
- src/projectman/hub does not exist and no module under src imports it
- projectman init has no --hub flag and add-project and set-branch and sync and migrate-hub
  and every --project option are gone from the CLI
- ProjectConfig has no hub or projects field and a legacy config.yaml carrying them
  still loads
- The tmp_hub fixture and every hub test file are gone and the full suite passes
created: '2026-09-08'
depends_on:
- US-PM-44
- US-PM-45
epic_id: EPIC-PM-6
id: US-PM-46
points: 5
priority: must
status: done
tags:
- subtraction
- hub
- cli
title: The hub package and its CLI and config keys are gone
updated: '2026-09-08'
---

As a maintainer, I want src/projectman/hub deleted with everything that reaches it so that the package has one store, one config shape and one init path, and the test suite no longer builds hubs it will never see.

State on 2026-09-08: src/projectman/hub holds registry.py (1,128 lines), migrate.py (849), stores.py (301), rollup.py (102). cli.py has init --hub (rendering architecture_hub.md.j2 and creating projects/), add-project, set-branch, sync, migrate-hub, and --project options on two commands; worktree.py carries hub-only comments and the add-project and migrate-hub attach paths; scoper.py, errors.py and store.py reference hub mode; ProjectConfig has hub: bool and projects: list[str] and config.yaml.j2 renders both. Test files: tests/test_hub.py, tests/test_hub_stores.py, tests/test_migrate_hub.py, tests/test_hub_pr_workflow_removed.py, tests/test_hub_troubleshooting_docs.py; the tmp_hub fixture in tests/conftest.py is used by 16 further files (archived_burndown_surfaces, feature_branch_workflow, audit_since_short_circuit, web_store_caching, indexer, tool_gating, store, scope, server_routing, worktree_git_ops, git_ops_after_subtraction, failure_classes_set_is_error, audit_state_digest and others) whose hub cases go and whose single-store cases stay.

A legacy config.yaml that still carries hub: or projects: must load without error (ignore the keys; a one-line warning is acceptable), because existing checkouts have them. This repo's own .project/config.yaml carries hub: false and projects: [] and must not be edited by a worker.

Depends on US-PM-44 and US-PM-45: the server, web, indexer and audit must stop importing the package before it is deleted so the suite never passes through a broken import.