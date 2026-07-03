---
assignee: null
created: '2026-03-06'
depends_on: []
id: US-PRJ-35-7
points: 1
status: todo
story_id: US-PRJ-35
tags: []
title: Add benchmark test for 5000+ item search
updated: '2026-03-06'
---

Create test that inserts 5000 dummy embeddings and measures search latency. Assert indexed search is at least 5x faster than brute-force at this scale.