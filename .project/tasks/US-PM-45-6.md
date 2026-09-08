---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-45-6
points: 1
status: done
story_id: US-PM-45
tags: []
title: Remove the hub README and badge builder from the indexer
updated: '2026-09-08'
---

In src/projectman/indexer.py delete _build_hub_readme, _workflow_badges and the is_hub branch so build_index and the index writer always produce INDEX.md for the one store; drop the imports of projectman.hub.stores and projectman.hub.rollup and the hub comment in the derived-file patterns. Remove the hub cases from tests/test_indexer.py and tests/test_indexes_are_derived.py, keeping the single-store ones. Run tests/test_indexer.py tests/test_indexes_are_derived.py tests/test_archived_burndown_surfaces.py.