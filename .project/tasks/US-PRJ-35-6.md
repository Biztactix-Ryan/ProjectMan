---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-35-6
points: 3
status: todo
story_id: US-PRJ-35
tags: []
title: Implement indexed vector search in embeddings.py
updated: '2026-03-06'
---

Replace the full table scan in embeddings.py search() with the chosen vector index. Build index on first search or on reindex. Store index file alongside embeddings.db. Fall back to brute-force scan if index missing.