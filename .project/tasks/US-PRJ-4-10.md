---
assignee: claude
created: '2026-02-17'
id: US-PRJ-4-10
points: 3
status: done
story_id: US-PRJ-4
title: Write tests for coordinated push workflow
updated: '2026-02-20'
---

Test the full push orchestration including failure scenarios.

1. **Happy path**: 3 dirty subprojects → preflight passes → all push → hub updated
2. **Preflight blocks**: one subproject on wrong branch → entire push aborted before anything is pushed
3. **Subproject push fails mid-way**: project 2 of 3 fails → project 1 recorded as pushed, project 3 skipped, hub NOT updated
4. **Hub push conflict**: subprojects push fine, hub push fails (simulate with concurrent commit) → error reported, subproject pushes preserved
5. **Dry run**: dirty projects detected, plan printed, nothing actually pushed
6. **No dirty projects**: everything clean → "nothing to push" message
7. **Selective push**: `--projects api,web` only pushes those two, ignores dirty worker
8. **Convention violations**: bad branch name on one project → preflight catches it, clear error

Use tmp_hub fixture with real git repos that have remotes (use bare repos as mock remotes).

Files: tests/test_hub.py or tests/test_coordinated_push.py