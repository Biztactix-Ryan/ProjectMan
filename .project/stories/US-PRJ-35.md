---
acceptance_criteria:
- Search uses indexed vector lookup instead of full table scan
- Performance acceptable for 5000+ items
- Backward compatible with existing embeddings.db
- FAISS or similar lightweight solution (no heavy external DB)
created: '2026-03-06'
epic_id: EPIC-PRJ-6
id: US-PRJ-35
points: 5
priority: could
status: backlog
tags:
- tier-2
- performance
- search
title: Add vector index for embedding search
updated: '2026-03-06'
---

As a user, I want semantic search to scale beyond 1000 items so that large projects don't have slow search. Currently embeddings.py does a full table scan with O(n×384) float operations per search query — no vector index exists.