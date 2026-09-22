---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-33-4
points: 1
status: done
story_id: US-PM-33
tags: []
title: Map coded errors to HTTP status in the web create endpoints
updated: '2026-09-06'
---

src/projectman/web/routes/api.py create_epic, create_story and create_task catch only FileNotFoundError, so the errors.ConflictError that US-PM-24 raises on an existing target ID surfaces as a 500. Add one helper in the web layer (e.g. _http_error(exc) in api.py or a small web/errors.py) that turns a ProjectManError into an HTTPException by its .code: conflict -> 409, not_found -> 404, invalid -> 422, permission -> 403, anything else -> 500, with detail {"error": code, "message": str(exc)}. Wrap the three create endpoints with it (keep the existing 404 messages for FileNotFoundError). A malformed ID passed as story_id or epic_id must come back 422 with error 'invalid'. Add tests in tests/web/test_create_conflicts.py: pre-create an item whose ID the next create would allocate (see tests/test_store_no_overwrite.py or the US-PM-24 tests for the setup), POST, assert 409 and the error code; a bad story_id on POST /tasks gives 422.