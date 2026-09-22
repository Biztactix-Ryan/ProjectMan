---
assignee: claude
created: '2026-08-22'
depends_on:
- US-PRJ-38-5
id: US-PRJ-38-7
points: 1
status: done
story_id: US-PRJ-38
tags: []
title: Invalidate the cached vector matrix on index writes and stale databases
updated: '2026-08-22'
---

The cached matrix from US-PRJ-38-5 must never serve stale results. Clear it whenever index_item() writes a row or reindex_all() runs, and guard against writes from another process by recording the embeddings.db mtime and row count at build time and rebuilding when either changes on the next search().

Acceptance: index_item followed by search() finds the new item without a restart; a second EmbeddingStore instance on the same db sees rows written by the first; covered by tests.

Files: src/projectman/embeddings.py, tests/test_embeddings.py.