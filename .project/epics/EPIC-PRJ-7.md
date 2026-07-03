---
created: '2026-03-09'
id: EPIC-PRJ-7
points: null
priority: must
status: draft
tags:
- performance
- caching
- v0.9
target_date: null
title: Performance & Caching Optimization
updated: '2026-03-09'
---

Address critical performance bottlenecks identified in the v0.8.3 major assessment. Key areas: excessive deep copying on every read, brute-force embedding search, N+1 query patterns in board/epic/search views, linear cache invalidation, full index rebuilds, and repeated git subprocess calls in hub mode. These issues compound at scale — projects with 1000+ items will see significant slowdowns.