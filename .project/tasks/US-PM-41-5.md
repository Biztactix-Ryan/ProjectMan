---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-41-4
- US-PM-38-4
- US-PM-38-5
id: US-PM-41-5
points: 2
status: todo
story_id: US-PM-41
tags: []
title: Re-point the tests that used generate_dashboards at rollup, delete the ones
  that only tested rendering
updated: '2026-09-06'
---

Ten test files mention dashboards (test_archived_burndown_surfaces, test_hub_epics, test_hub_unattached, test_git_ops_after_subtraction, test_migrate_hub, test_cli, test_init_attach, test_failure_classes_set_is_error, test_feature_branch_workflow, conftest). For each: if the test asserts a rollup fact (points, not-attached rows, epic counts) through generate_dashboards or the rendered README, rewrite it to call projectman.hub.rollup.rollup and assert on the dict; if it only checks the module's own markdown output or that init made a dashboards dir, delete it (not skip). Remove any conftest fixture that existed only for dashboards. Run the full unit suite and confirm the failure set is exactly the known environment-blocked ones once US-PM-38 lands.