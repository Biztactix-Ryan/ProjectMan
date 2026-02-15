---
assignee: null
created: '2026-02-15'
id: US-PRJ-5-3
points: 2
status: done
story_id: US-PRJ-5
title: Write tests for tasks, board, docs, and error cases
updated: '2026-02-15'
---

Test the following endpoints:
- CRUD lifecycle for tasks: POST create → GET read → GET list with ?story_id= filter → PATCH update → POST grab → DELETE archive
- Board endpoint: GET `/api/board` returns grouped tasks
- Burndown: GET `/api/burndown` returns point data
- Audit: GET `/api/audit` returns findings
- Search: GET `/api/search?q=` returns results
- Docs: GET `/api/docs`, GET `/api/docs/{name}`, PUT `/api/docs/{name}`
- Hub mode: verify `?project=` parameter forwarding on key endpoints