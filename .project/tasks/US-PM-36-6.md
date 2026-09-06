---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-36-6
points: 2
status: done
story_id: US-PM-36
tags: []
title: Hub-only epic creation and epic_id links validated against the hub store
updated: '2026-09-06'
---

In server.py pm_create_epic: in a hub always write to the hub's own store and drop the prefix parameter (outside a hub behaviour is unchanged; a prefix passed in a hub is a coded invalid error naming the rule). Add _validate_epic_link(epic_id) in server.py: resolve the epic's store with _store_for_id(epic_id) and get_epic it; a missing epic is errors.NotFoundError (not_found) that names the hub and the story's own store as the places searched. Call it from pm_create_story(epic_id=...) and pm_update(epic_id=...) before writing. Audit check 9 (orphaned-epic-reference in src/projectman/audit.py) must accept a hub-prefixed epic_id on a subproject store: give run_audit an optional known_epic_ids argument that server.pm_audit fills with the hub store's epic IDs in a hub. Tests in tests/test_hub_epics.py with a two-store hub fixture (tests/test_add_project_worktree.py has one): pm_create_epic writes only under the hub's .project/epics and the subproject epics dir gains no file; a subproject story can set epic_id to the hub epic; an epic_id unknown to both stores is not_found; single-project create/link behaviour has an unchanged regression test.