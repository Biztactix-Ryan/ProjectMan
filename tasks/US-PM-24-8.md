---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-24-7
id: US-PM-24-8
points: 1
status: done
story_id: US-PM-24
tags: []
title: pm_fix_malformed and pm_restore refuse an existing target
updated: '2026-09-05'
---

Found by the US-PM-24-3 verification: in src/projectman/server.py, pm_fix_malformed writes `dest.write_text(...)` at a caller-supplied id with no exists check, and pm_restore does a `shutil.move` over `stories/<filename>` that silently replaces a live story. Both create an item file and must follow the same rule as Store.create_*: if the target exists, return the tool's standard error result (FileExistsError -> ToolError, 'already exists') without touching the target, and write through _atomic_write_text where a write happens. Flip the two strict xfails in tests/test_creates_never_overwrite.py into ordinary passing tests and extend the failure-class inventory if those tools are enumerated there. Do not change pm_fix_malformed's or pm_restore's behaviour when the target does not exist.