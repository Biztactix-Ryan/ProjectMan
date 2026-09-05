---
archived: false
assignee: claude
claimed_at: '2026-09-04T23:43:11.699727+00:00'
claimed_by_run: orch-2026-09-05-1167
created: '2026-09-05'
depends_on: []
id: US-PM-27-6
points: 3
status: done
story_id: US-PM-27
tags: []
title: 'Pass 1: remove changesets end to end'
updated: '2026-09-05'
---

Delete src/projectman/changesets.py and its models in models.py (ChangesetFrontmatter, ChangesetStatus, entry types); remove `next_changeset_id` from config.py and the config template; remove the changesets dir handling and create/get/list/update_changeset from store.py; remove the five pm_changeset_* tools from server.py (lines ~4077-4230) and the `changesets` / `changesets_by_status` keys from pm_status; remove the `changeset` click group and `changeset-status` command from cli.py; remove is_project_blocked_by_changeset and get_changeset_context from hub/registry.py and their call sites. Delete tests/test_changeset.py and tests/test_changeset_pr_commands.py and any changeset cases elsewhere. Existing .project/changesets dirs on disk must be tolerated (ignored) by the store so old projects still load. Run the full unit suite with the uv command in the project notes before reporting.