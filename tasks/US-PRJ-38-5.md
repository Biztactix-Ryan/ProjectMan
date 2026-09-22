---
assignee: claude
created: '2026-08-22'
depends_on: []
id: US-PRJ-38-5
points: 2
status: done
story_id: US-PRJ-38
tags: []
title: Batch-decode embedding rows into one cached numpy matrix
updated: '2026-08-22'
---

In src/projectman/embeddings.py add a lazily-built in-memory view of the embeddings table: a single np.ndarray of shape (n, dim) plus parallel lists of ids, titles and types, built from one SELECT on the first search() call and cached on the EmbeddingStore instance (e.g. self._matrix, self._rows). Decoding must happen once per row per cache build (np.frombuffer over the concatenated blobs, or one decode per row into a preallocated array), never inside the per-query loop.

Acceptance: vectors are decoded once, not per search; a second search() on an unchanged index performs no SQLite reads of the vector column; existing tests in tests/test_embeddings.py still pass.

Files: src/projectman/embeddings.py, tests/test_embeddings.py.