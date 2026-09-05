---
acceptance_criteria:
- No pm_changeset tool or changeset CLI command exists and the changesets module is
  gone
- hub/registry.py no longer contains feature-branch or PR or hub-ref-update or rebase-conflict
  code
- pm_commit and pm_push and pm_git_status behave as before on this repo and their
  tests pass
- Hub docs no longer describe changesets or the PR workflow
- Full unit suite passes with the removed tests deleted rather than skipped
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-27
points: 8
priority: must
status: done
tags:
- hub
- changesets
- subtraction
title: Changesets and the hub PR workflow are removed from the main package
updated: '2026-09-05'
---

As a maintainer, I want the cross-repo changeset and hub pull-request machinery out of ProjectMan so that a quarter of the code and tests stop taxing every change to a feature that was called 9 times in 484 sessions.

What goes:
- src/projectman/changesets.py, the changeset models in models.py, `next_changeset_id` in config, the changeset counts in pm_status, the five pm_changeset_* MCP tools in server.py, the `changeset` CLI group and `changeset-status` command in cli.py.
- In src/projectman/hub/registry.py (3,609 lines): feature-branch creation and listing, create_pr / get_pr_status, update_hub_refs and update_hub_refs_after_merge, hub_push_with_rebase and the submodule-ref conflict resolution, is_project_blocked_by_changeset / get_changeset_context, and the deploy-branch validation that only existed to serve PRs.
- Their tests: tests/test_changeset.py, test_changeset_pr_commands.py, test_hub_pr_workflow.py, test_hub_ref_update_after_merge.py, test_update_hub_refs_after_merge.py, test_hub_conflicts.py, and the parts of test_hub.py that cover the removed functions.
- Docs under docs/hub-mode that describe changesets and PR flow.

What stays: pm_commit, pm_push, pm_git_status and coordinated_push with whatever registry helpers they actually need; hub/rollup.py and hub/dashboards.py (the read-only rollup the future hub redesign builds on); the `hub` config flag; add_project / sync / repair only if pm_commit or pm_push still call them.

Do it in three passes so each is reviewable: changesets first, then the PR workflow, then the docs and dead-import sweep. Run the full unit suite after each pass. Record the before/after line counts for source and tests in the run log.