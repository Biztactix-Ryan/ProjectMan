---
assignee: claude
created: '2026-02-17'
id: US-PRJ-7-11
points: 3
status: done
story_id: US-PRJ-7
title: Write tests for PR workflow end-to-end
updated: '2026-02-28'
---

Test the full PR workflow using tmp_hub fixture with real git repos.

1. **Feature branch creation**: create_feature_branch() produces correct naming, refuses to branch from non-deploy, refuses on dirty tree
2. **PR creation**: Mock or stub `gh` CLI calls, verify correct --base and --head flags
3. **Hub ref update**: After simulated merge, update_hub_refs() moves submodule ref forward. With open PRs, ref stays put.
4. **Deploy protection**: validate_not_on_deploy_branch() catches direct commits to deploy, allows commits on feature branches
5. **Multi-project**: Simultaneous feature branches in 3 subprojects, PRs created for all, hub refs updated only for merged ones
6. **Edge cases**: No gh installed, subproject has no remote, deploy branch doesn't exist on remote

Files: tests/test_hub.py or tests/test_hub_pr_workflow.py