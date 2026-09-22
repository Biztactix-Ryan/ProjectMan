---
assignee: claude
created: '2026-03-06'
depends_on: []
id: US-PRJ-29-7
points: 1
status: done
story_id: US-PRJ-29
tags: []
title: Remove or integrate validate_dependencies() from deps.py
updated: '2026-03-09'
---

validate_dependencies() at deps.py:137-173 is never called in production. Either remove it entirely (and its tests) or integrate it as a pre-check in store._validate_depends_on(). If integrating, replace store's manual validation with the deps.py version.