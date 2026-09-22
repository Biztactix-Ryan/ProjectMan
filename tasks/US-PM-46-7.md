---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-46-5
- US-PM-46-6
id: US-PM-46-7
points: 2
status: done
story_id: US-PM-46
tags: []
title: Delete src/projectman/hub and every hub test and the tmp_hub fixture
updated: '2026-09-08'
---

Delete src/projectman/hub entirely (registry.py, migrate.py, stores.py, rollup.py, __init__.py). Delete tests/test_hub.py, tests/test_hub_stores.py, tests/test_migrate_hub.py, tests/test_hub_pr_workflow_removed.py, tests/test_hub_troubleshooting_docs.py. Remove the tmp_hub fixture from tests/conftest.py and every hub case from the files that used it (test_archived_burndown_surfaces, test_feature_branch_workflow, test_audit_since_short_circuit, test_web_store_caching, test_indexer, test_tool_gating, test_store, test_scope, test_server_routing, test_worktree_git_ops, test_git_ops_after_subtraction, test_failure_classes_set_is_error, test_audit_state_digest), keeping their single-store cases. grep src for 'projectman.hub' and 'from .hub' and confirm zero hits. Add a source-scan test asserting no module under src imports projectman.hub. Run the full suite minus tests/integration; it must pass.