---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-53-6
points: 3
status: done
story_id: US-PM-53
tags: []
title: Add lane compatibility to the store and a lane_compatible_with filter on pm_board
updated: '2026-09-09'
---

deps.py (or store.py) gains lane_compatible(store, in_flight_id, candidate_id) -> bool: false when the two tasks share a story, when either depends on the other or on the other's story, or when their stories are connected by any depends_on path in either direction; true otherwise. pm_board gains `lane_compatible_with: Optional[str]` that filters the available list through it and returns `lane_excluded: n` so the caller knows work was hidden. Tests in tests/test_deps.py with a small dependency graph covering each rule.