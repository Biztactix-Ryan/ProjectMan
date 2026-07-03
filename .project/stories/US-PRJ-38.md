---
acceptance_criteria:
- Vectors batch-decoded into numpy array once
- Cosine similarity uses np.dot(Q; all_vecs.T) instead of loop
- First search lazy-loads and caches decoded vectors
- 10x+ improvement for 1000-item projects
created: '2026-03-09'
epic_id: EPIC-PRJ-7
id: US-PRJ-38
points: 5
priority: must
status: backlog
tags:
- performance
- search
title: Replace brute-force embedding search with vectorized operations
updated: '2026-03-09'
---

As a user running semantic search, I want queries to complete quickly so that search remains responsive as project size grows. Currently embeddings.py lines 103-121 do a full table scan, decode every vector individually, and compute cosine similarity in a Python loop. Should batch-decode into numpy array and use vectorized dot product.