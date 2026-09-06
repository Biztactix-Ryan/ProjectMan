---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-35-6
points: 3
status: done
story_id: US-PM-35
tags: []
title: Delete the cross-project push, repair and branch-validation machinery and its
  tests
updated: '2026-09-06'
---

Remove from src/projectman/hub/registry.py: coordinated_push, push_subprojects, hub_push_with_rebase, push_hub, push_preflight, repair, validate_branches, format_branch_validation, validate_not_on_deploy_branch, _discover_dirty_projects, _has_unpushed_commits, _push_subproject, _push_store_branch, _generate_hub_commit_message if unreferenced, and every private helper that becomes unreferenced (run a grep after each pass). Remove the CLI commands push-all, repair and validate-branches from src/projectman/cli.py and the pm_push_all MCP tool from server.py (and its entry in the tool-gating/annotation lists). Record registry.py line count before (2714) and after in the run-log note. Delete the tests of the removed code rather than skipping them: tests/test_coordinated_push.py and tests/test_hub_validation.py whole; the individual tests in tests/test_hub.py, test_deploy_branch_protection.py, test_feature_branch_workflow.py, test_hub_conflicts.py, test_genuine_failures_raise.py, test_tool_gating.py, test_tool_annotations.py, test_hub_pr_workflow_removed.py and test_docs_after_subtraction.py that exercise a removed function or command. Do not touch pm_commit, pm_push, sync, add_project, set_branch, list_projects or git_status_all in this task; they change in the next two. Full unit suite passes at the end (uv run command in docs/installation.md).