---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-27-6
id: US-PM-27-7
points: 3
status: done
story_id: US-PM-27
tags: []
title: 'Pass 2: remove the hub PR and ref-update workflow from registry.py'
updated: '2026-09-05'
---

In src/projectman/hub/registry.py remove: create_feature_branch, list_feature_branches, _slugify, create_pr, get_pr_status, _get_open_prs, update_hub_refs, update_hub_refs_after_merge, hub_push_with_rebase, _analyze_remote_changes, _classify_rebase_conflict, check_ref_fast_forward, _get_conflicting_submodule_refs, _resolve_submodule_ref_conflict, log_ref_update, validate_not_on_deploy_branch, set_deploy_branch, _get_deploy_branch — unless pm_commit, pm_push, coordinated_push, git_status_all or validate_branches still call them, in which case keep the minimum and say so in the run log. Remove the matching MCP tools and CLI commands that only exposed those functions. Delete tests/test_hub_pr_workflow.py, test_hub_ref_update_after_merge.py, test_update_hub_refs_after_merge.py, test_hub_conflicts.py and the removed-function cases in test_hub.py. pm_commit, pm_push and pm_git_status tests must still pass. Never run pm_push or any push against the real repo.