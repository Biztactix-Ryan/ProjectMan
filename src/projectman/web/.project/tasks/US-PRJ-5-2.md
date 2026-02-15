---
assignee: null
created: '2026-02-15'
id: US-PRJ-5-2
points: 2
status: done
story_id: US-PRJ-5
title: Write tests for project, epics, and stories CRUD endpoints
updated: '2026-02-15'
---

Test the following endpoints:
- GET `/api/status` — returns valid status JSON
- GET `/api/config` — returns config
- CRUD lifecycle for epics: POST create → GET read → PATCH update → DELETE archive
- CRUD lifecycle for stories: POST create → GET read → GET list with ?status= filter → PATCH update → DELETE archive
- Error cases: 404 for missing items, 422 for invalid input (bad points, missing required fields)