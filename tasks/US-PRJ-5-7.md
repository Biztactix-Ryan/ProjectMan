---
assignee: claude
created: '2026-02-17'
id: US-PRJ-5-7
points: 2
status: done
story_id: US-PRJ-5
title: Write tests for auto-commit behavior
updated: '2026-02-20'
---

Test auto-commit across mutation types and config states.

1. **Enabled + create story**: auto_commit=True, create a story → git log shows commit with `pm: create US-PRJ-X`
2. **Enabled + update task**: update task status → commit with `pm: update US-PRJ-X-X status=done`
3. **Disabled**: auto_commit=False, create story → no new commit, file is untracked
4. **Only .project/ files**: auto_commit=True, but other files are dirty → only .project/ files in the commit
5. **Not a git repo**: auto_commit=True but no .git dir → mutation succeeds, warning logged, no crash
6. **No auto-push**: after auto-commit, verify `git log origin/main..HEAD` shows unpushed commit
7. **Hub mode subproject**: auto_commit in subproject config overrides hub setting

Files: tests/test_auto_commit.py