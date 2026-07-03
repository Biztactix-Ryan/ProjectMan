---
assignee: claude
created: '2026-02-17'
id: US-PRJ-8-9
points: 2
status: done
story_id: US-PRJ-8
title: Write tests for git status dashboard
updated: '2026-02-28'
---

Test data collection, formatting, and edge cases.

1. **All clean**: 3 subprojects all on deploy branch, clean, up to date → no issues
2. **Mixed state**: one dirty, one misaligned, one behind → correct issues reported, sorted by severity
3. **Detached HEAD**: submodule in detached state → detected and reported
4. **Ahead/behind counts**: subproject 3 ahead, 2 behind → correct counts
5. **Missing project**: registered in config but dir doesn't exist → reported as missing, doesn't crash
6. **No remote**: subproject has no remote configured → ahead/behind shows N/A, doesn't crash
7. **20+ projects**: Performance test — verify parallel git calls complete in reasonable time
8. **PR data unavailable**: gh not installed or not authed → graceful degradation, core status still works

Files: tests/test_hub.py or tests/test_git_status.py