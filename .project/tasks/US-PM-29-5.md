---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-29-4
id: US-PM-29-5
points: 2
status: todo
story_id: US-PM-29
tags: []
title: Readers of index.yaml rebuild when it is older than the newest item file
updated: '2026-09-06'
---

Find every consumer of index.yaml: cli.py init (around line 195 writes it), store.py (around line 2917 treats it as a known file), the web dashboard and routes, and hub/rollup.py which calls build_index directly. Each must either read from the Store or call a new indexer.ensure_fresh(store) that rebuilds when index.yaml's mtime is older than the newest file under epics/, stories/ or tasks/. No reader may serve stale counts after a write that skipped reindexing. Files: src/projectman/indexer.py, src/projectman/cli.py, src/projectman/store.py, src/projectman/web/.