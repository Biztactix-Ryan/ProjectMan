---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-35-6
id: US-PM-35-8
points: 2
status: done
story_id: US-PM-35
tags: []
title: pm_git_status reads each store through the worktree helpers and sync re-attaches
  missing stores
updated: '2026-09-06'
---

In registry.py rewrite _collect_project_status / git_status_all so each subproject row comes from worktree.store_git_state on the attached store path (branch, dirty count, ahead/behind, attached flag, last commit), keeping the submodule's own checkout branch as a second column; drop the deploy-branch alignment fields (aligned, deploy_branch, branch_ok) and the severity scoring that depended on them, and update format_git_status accordingly. pm_git_status in server.py keeps its prefix filter. Rewrite registry.sync to: drop the validate_branches pre-check, fast-forward pull every checked-out submodule (skip dirty ones with a warning, as now), then for every registered project whose store worktree is missing call worktree.attach_worktree (or ensure_store_branch when the branch is absent) and report what was attached. Update the sync entry in docs/reference/cli.md. Tests in tests/test_hub_git_status.py and an extension of tests/test_migrate_hub.py or test_add_project_worktree.py: status rows show the store branch and ahead/behind from a fixture with one commit unpushed; sync on a hub where one store worktree was removed re-attaches it and says so.