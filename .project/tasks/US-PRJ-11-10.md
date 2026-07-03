---
assignee: claude
created: '2026-02-17'
id: US-PRJ-11-10
points: 3
status: done
story_id: US-PRJ-11
title: Write tests for hub conflict resolution
updated: '2026-02-19'
---

Test auto-rebase and fast-forward scenarios with real git repos.

1. **Clean push**: no conflict → pushes first try, 0 retries
2. **Simple rebase**: remote has new commit (different submodule ref) → auto-rebase succeeds, push on retry
3. **Same-project fast-forward**: both update api ref, ours is newer → auto-resolved, ours kept
4. **Same-project theirs-newer**: both update api ref, theirs is newer → auto-resolved, theirs kept
5. **Diverged refs**: both update api ref, branches diverged → flagged for manual resolution, clear error message
6. **Max retries exceeded**: simulate continuous remote pushes → fails after 3 retries, reports clearly
7. **.project/ file conflict**: both modify same story file → rebase conflict on non-submodule file, abort with message
8. **Ref log**: after successful push, ref-log.yaml contains entry with old/new ref, timestamp, source
9. **Ref log rotation**: 501 entries → oldest rotated to archive

Setup: create bare repos as remotes, simulate concurrent pushes by committing directly to the bare repo between operations.

Files: tests/test_hub_conflicts.py