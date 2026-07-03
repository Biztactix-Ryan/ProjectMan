---
acceptance_criteria:
- installation.md embeddings row shows fastembed not sentence-transformers
- All other optional dependency entries verified against pyproject.toml
created: '2026-03-09'
epic_id: EPIC-PRJ-10
id: US-PRJ-53
points: 1
priority: must
status: done
tags:
- docs
title: Fix installation.md wrong package reference
updated: '2026-03-09'
---

As a new user installing ProjectMan, I want correct dependency documentation so that pip install works. installation.md line 88 lists sentence-transformers but the actual dependency is fastembed (pyproject.toml and embeddings.py both use fastembed). Fix the optional dependencies table.