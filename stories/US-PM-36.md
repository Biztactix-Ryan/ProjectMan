---
acceptance_criteria:
- In a hub pm_create_epic writes only to the hub store and a subproject store never
  gains a new epic file
- A subproject story can set epic_id to a hub epic and an epic_id that exists in neither
  the hub nor the story's own store is a coded not_found error
- pm_epic on a hub epic rolls up stories and points from every subproject store grouped
  by project
- migrate-hub moves subproject-local epics to the hub with hub-prefixed IDs and rewrites
  every affected story's epic_id and prints the old-to-new mapping
- Single-project epic behaviour is unchanged
created: '2026-09-06'
depends_on:
- US-PM-34
epic_id: EPIC-PM-5
id: US-PM-36
points: 5
priority: should
status: done
tags:
- hub
- epics
title: Epics exist at hub level only and roll up stories from every subproject
updated: '2026-09-06'
---

As a hub maintainer, I want one place to write an epic that spans several repos, so that the docs' promise of cross-project epics is what the store actually does instead of each subproject keeping its own EPIC-{PREFIX}-N files.

docs/hub-mode/epics.md describes epics as cross-project initiatives, but every store has its own epics directory and pm_epic only rolls up stories in the same store. After US-PM-34 an epic ID's prefix names a store, so a hub epic is simply one whose prefix is the hub's.

Direction: in a hub, pm_create_epic writes to the hub store only and takes no prefix; a subproject story may set epic_id to a hub epic and the link is validated against the hub store; pm_epic on a hub epic gathers stories from every store in the map and groups the rollup by project; pm_status and the dashboards count epics once. projectman migrate-hub (US-PM-31) gains a step that moves subproject-local epics up to the hub, renumbering them with the hub prefix and rewriting every story's epic_id, and records the mapping in the migration output. Single-project mode is unchanged.