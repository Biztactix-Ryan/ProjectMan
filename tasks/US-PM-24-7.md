---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-24-5
- US-PM-24-6
id: US-PM-24-7
points: 2
status: done
story_id: US-PM-24
tags: []
title: Every create refuses an existing target and writes atomically
updated: '2026-09-05'
---

For create_story (~820), create_task (~1718), create_tasks (~1795), create_epic (~1557), create_sprint (~2555) and create_changeset (~2452): before writing, `if path.exists(): raise FileExistsError(f"{id} already exists")`; write through the existing `_atomic_write_text` helper (line 351) instead of `Path.write_text`. Leave update paths alone (they intentionally overwrite). In create_tasks the rollback-on-cycle path must still work after the switch. Unit test: pre-create the file the next ID would map to and assert FileExistsError with no content change.