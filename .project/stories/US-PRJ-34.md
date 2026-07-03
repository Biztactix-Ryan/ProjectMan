---
acceptance_criteria:
- rollup() uses ThreadPoolExecutor for parallel project scanning
- Max workers capped similar to git_status_all (min(projects 16))
- Results identical to sequential version
- Performance improvement measurable on 5+ project hubs
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-34
points: 3
priority: should
status: backlog
tags:
- tier-2
- performance
- hub
title: Parallelize hub rollup
updated: '2026-03-06'
---

As a hub user, I want rollup to be fast across many projects so that dashboards don't take 10+ seconds to generate. Currently rollup() scans projects sequentially. git_status_all() already uses ThreadPoolExecutor — rollup should follow the same pattern.