---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-36-6
id: US-PM-36-7
points: 2
status: done
story_id: US-PM-36
tags: []
title: pm_epic on a hub epic rolls up stories from every store grouped by project
updated: '2026-09-06'
---

In server.py pm_epic: when the epic's store is the hub store in a hub, collect linked stories from every store in _prefix_map (hub plus each attached subproject; unattached stores are listed by name with a note, not skipped silently), build tasks_by_story per store, and return the rollup with total_points, completed_points and story counts overall plus a by_project list ({name, prefix, stories, total_points, completed_points}); the paginated story detail keeps limit/offset over the flattened list with each story tagged by project. Outside a hub, or for a subproject epic, the output shape is unchanged. Epic counting: in hub/rollup.py count total_epics as the hub store's epics plus subproject epics (so a not-yet-migrated hub still adds up) but pm_status with no prefix in a hub must report the hub's own epic count once; check hub/dashboards.py renders the per-project epic column from the rollup without double counting. Tests in tests/test_hub_epics.py: hub epic with stories in two subprojects rolls up points grouped by project; limit/offset paginate across projects; a single-project epic view is byte-identical to before.