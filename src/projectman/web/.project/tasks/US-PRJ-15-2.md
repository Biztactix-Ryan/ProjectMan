---
assignee: null
created: '2026-02-15'
id: US-PRJ-15-2
points: 1
status: done
story_id: US-PRJ-15
title: Wire HTMX response triggers to toast handler
updated: '2026-02-15'
---

Connect API responses to toast notifications:
- API endpoints set `HX-Trigger` response headers on success/error (e.g., `{"showToast": {"message": "Story created", "type": "success"}}`)
- HTMX `htmx:trigger` event listener in `app.js` picks up triggers and shows toast
- Wire all create/update/delete operations to trigger appropriate toasts
- Error responses (4xx/5xx) trigger error toasts with message