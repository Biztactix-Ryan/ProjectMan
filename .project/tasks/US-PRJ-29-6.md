---
assignee: claude
created: '2026-03-06'
depends_on: []
id: US-PRJ-29-6
points: 2
status: done
story_id: US-PRJ-29
tags: []
title: Refactor store.py _check_dependency_cycles to use deps.detect_cycle()
updated: '2026-03-09'
---

Replace the visited+in_stack DFS in store.py:669-691 with a call to deps.detect_cycle(). Build the graph the same way, but delegate detection to the canonical implementation. Wrap the result in ValueError with the full cycle path string.