---
assignee: claude
created: '2026-08-22'
depends_on:
- US-PRJ-38-5
id: US-PRJ-38-6
points: 2
status: done
story_id: US-PRJ-38
tags: []
title: Replace the per-row similarity loop with a vectorised top-k
updated: '2026-08-22'
---

Rewrite EmbeddingStore.search() to compute scores as a single matrix-vector product (matrix @ query_vec — vectors are already normalised so this is cosine similarity) and select top_k with np.argpartition followed by a sort of the k candidates, instead of building an EmbeddingResult per row and sorting the whole list. Return value shape and EmbeddingResult fields are unchanged.

Add a synthetic benchmark test (1000 random normalised vectors inserted directly into the sqlite table, no model calls) that times the old loop formulation against the new search() and asserts >=10x speedup; mark it so it can be skipped in CI if timing is noisy.

Acceptance: search ranking is identical to the previous implementation for the same index (test with a fixed seed); benchmark shows >=10x for 1000 items.

Files: src/projectman/embeddings.py, tests/test_embeddings.py or a new tests/test_embeddings_perf.py.