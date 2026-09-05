---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on:
- US-PRJ-48-5
id: US-PRJ-48-6
points: 3
status: done
story_id: US-PRJ-48
tags: []
title: Raise the taxonomy from store.py and worktree.py at every raise site
updated: '2026-09-05'
---

src/projectman/store.py has 24 raise sites (11 ValueError, 9 FileNotFoundError, 3 RuntimeError, 1 NothingToCommit) — replace each with the matching errors.py class, keeping the message text identical. Map: item-not-found -> NotFoundError; bad status/points/ID/payload -> ValidationError; already-claimed, dependency cycle, NothingToCommit -> ConflictError; git/IO failures -> StoreError. Do the same for worktree.MigrationError (subclass StoreError). Because each class also subclasses the builtin it replaces, existing except ValueError/FileNotFoundError handlers in server.py, cli.py and tests keep working. Run the full suite (uv run --with 'mcp<2' pytest) and confirm zero regressions.