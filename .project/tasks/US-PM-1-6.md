---
assignee: null
created: '2026-07-30'
depends_on: []
id: US-PM-1-6
points: 1
status: todo
story_id: US-PM-1
tags: []
title: Clear the stale port-forward markers left by the 0.8.15 rebase
updated: '2026-07-30'
---

Sprint 1 was authored against a base without pm_done_next and left "NOTE (port forward)" markers at every site that would need revisiting. After the rebase onto 0.8.15 three of the four are done in code but their comments were never updated, so the source now misdescribes itself.

Stale and needing removal/rewrite:
- src/projectman/server.py:277 — id/task_id alias note; pm_done_next already calls _resolve_id("task_id", task_id, id=id), so the note is wrong.
- tests/test_note_truncated_flag.py, tests/test_oversized_note_write_lands.py, tests/test_note_flag_boundary.py — headers claiming pm_done_next does not exist.
- docs/reference/readiness-warnings-determination.md:252 — cites server.py:87 as a port-forward.
- docs/reference/error-paths-inventory.md:483 — table row marked "n/a - port forward" for pm_done_next, which now routes through _failed.

Leave the server.py:87 OUTSTANDING marker in place until US-PM-1-3 lands; that one is still accurate. Verify with a repo-wide grep for "port forward" that nothing false remains.