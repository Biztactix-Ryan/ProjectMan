---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-44-5
id: US-PM-44-6
points: 2
status: done
story_id: US-PM-44
tags: []
title: Remove every hub-conditioned branch from the tool bodies
updated: '2026-09-08'
---

In server.py remove the code paths guarded by load_config(root).hub or config.hub: pm_status subprojects list and hint, pm_epic by_project rollup and not_attached list (pm_epic answers from the one store), pm_burndown hub rollup import, pm_git_status git_status_all import, pm_malformed and pm_reindex and pm_restore hub loops, pm_context hub docs and hub-level vision/architecture merge, pm_audit project_dir and known_epic_ids plumbing (audit.py's own signature change is US-PM-45). Delete tests/test_hub_routing.py, test_hub_epics.py, test_hub_unattached.py, test_hub_commit_push_prefix.py, test_hub_git_status.py, test_hub_conflicts.py and the hub cases of tests/test_server_routing.py. Add or keep a test that pm_status, pm_epic, pm_burndown, pm_git_status, pm_malformed and pm_context responses carry no subprojects, by_project or not_attached keys. Run the full suite minus tests/integration.