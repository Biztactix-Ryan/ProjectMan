---
created: '2026-03-09'
id: EPIC-PRJ-9
points: null
priority: must
status: draft
tags:
- quality
- security
- v0.9
target_date: null
title: Code Quality, Safety & Error Handling
updated: '2026-03-09'
---

Address code quality issues found in the v0.8.3 assessment: shell injection risk in changesets PR command generation, inconsistent error handling (generic except Exception across 41 tools), incomplete destructive annotations on push/restore/fix_malformed tools, ID format validation gaps in models, thread safety concerns with global mutable cache state, and datetime handling inconsistencies.