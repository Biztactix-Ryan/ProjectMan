---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-34-5
points: 2
status: todo
story_id: US-PRJ-34
tags: []
title: Refactor rollup() to use ThreadPoolExecutor
updated: '2026-03-06'
---

In hub/rollup.py, replace the sequential for-loop over projects with ThreadPoolExecutor, following the same pattern as git_status_all() in registry.py. Cap max_workers at min(len(projects), 16). Each worker builds index for one project.