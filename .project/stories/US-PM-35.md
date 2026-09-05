---
acceptance_criteria:
- hub/registry.py no longer contains coordinated_push or push_subprojects or hub_push_with_rebase
  or push_hub or repair or validate_branches and the push-all and repair and validate-branches
  CLI commands are gone
- pm_commit and pm_push in a hub act on the one store named by prefix and land commits
  on that subproject's projectman branch
- pm_git_status in a hub reports each subproject store's branch and dirty and ahead-behind
  state through the worktree helpers
- projectman sync pulls every submodule and re-attaches any store whose worktree is
  missing
- Removed tests are deleted rather than skipped and the full unit suite passes
created: '2026-09-06'
depends_on:
- US-PM-34
epic_id: EPIC-PM-5
id: US-PM-35
points: 5
priority: should
status: backlog
tags:
- hub
- subtraction
- git
title: 'The hub is a read-only rollup: cross-project commit, push and repair leave
  the package'
updated: '2026-09-06'
---

As a hub maintainer, I want the hub to aggregate and display what each subproject's projectman branch says, and nothing more, so that the 2.5k-line hub/registry.py stops orchestrating git across repos it does not own.

Once US-PM-31 puts each store on its own branch and US-PM-34 routes by prefix, a write to US-API-3 is committed and pushed inside projects/api by the ordinary pm_commit and pm_push against that store, exactly as single-project mode does today. The hub-level machinery that existed to commit and push on behalf of subprojects becomes dead: coordinated_push, push_subprojects, hub_push_with_rebase, push_hub, push_preflight, repair, validate_branches and their CLI commands push-all, repair and validate-branches. sync remains as the one hub-wide git verb (pull every submodule and re-attach stores). add-project, set-branch, list_projects and git_status_all stay, with git_status_all reading each store's state through worktree.store_git_state.

Direction: delete the dead functions and commands and their tests rather than skipping them, keep the `scope` parameter on pm_commit and pm_push only as `prefix`, and record the before and after line counts of registry.py in the run log.