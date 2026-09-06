---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-36-6
id: US-PM-36-8
points: 2
status: done
story_id: US-PM-36
tags: []
title: migrate-hub moves subproject epics up to the hub and rewrites story links
updated: '2026-09-06'
---

In src/projectman/hub/migrate.py add an epics step to migrate_hub that runs after the store move (and also on a hub whose stores already live at projects/{name}/.project, so it can be run on its own): for each subproject store, move every epics/EPIC-{P}-N.md to the hub store as EPIC-{HUB}-M using the hub store's _next_epic_id, rewrite epic_id on every story in every store that referenced the old ID, bump next_epic_id in the hub config, and commit in each affected store and the hub with a message naming the mapping. Print the old-to-new mapping in format_migration; --dry-run lists the planned moves; a hub with no subproject epics reports nothing to move and exits 0. The hub's index files are rebuilt after the move. Tests in tests/test_migrate_hub.py: two subproject stores with one epic each and stories linked from both become two hub epics with all epic_id links rewritten and the mapping printed; re-running is a no-op; dry-run changes nothing.