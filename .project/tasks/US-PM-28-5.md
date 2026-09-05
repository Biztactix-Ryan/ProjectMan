---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on: []
id: US-PM-28-5
points: 2
status: done
story_id: US-PM-28
tags: []
title: Store next-note methods and the pm_next MCP tool
updated: '2026-09-05'
---

store.py: `next_note_path` -> .project/NEXT.md; `read_next() -> str | None`; `write_next(text, append=False)` (append adds a blank line, a `### <ISO date>` heading and the text); `clear_next()`. Emit one activity event per write/clear (EventType.update on item 'NEXT' or a new event type if the log schema requires a real item id — check activity_log.py). server.py: `pm_next(text: str | None = None, append: bool = False, clear: bool = False, project=None)` returning `{note: ...}` or `{note: null, message: 'no note saved'}`; text together with clear is a ValueError with a clear message; annotate the tool as non-destructive except when clear=true (mirror how other tools set destructiveHint). Tests in tests/test_server.py using the tmp_project fixture only.