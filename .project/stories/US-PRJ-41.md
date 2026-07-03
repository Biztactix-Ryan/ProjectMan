---
acceptance_criteria:
- Status collection uses max 2 git calls per project instead of 4+
- ThreadPoolExecutor still used for parallelism
- Results match current output format
created: '2026-03-09'
epic_id: EPIC-PRJ-7
id: US-PRJ-41
points: 5
priority: could
status: backlog
tags:
- performance
- hub
title: Optimize hub git subprocess calls with batching
updated: '2026-03-09'
---

As a hub operator, I want status collection to be fast so that pm_git_status responds quickly with many subprojects. Currently hub/registry.py makes 4+ separate git subprocess calls per project (_get_ahead_behind, _get_dirty_count, _get_last_commit, _get_open_prs). Batch into fewer calls per project.