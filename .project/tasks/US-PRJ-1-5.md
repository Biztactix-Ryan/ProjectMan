---
assignee: claude
created: 2026-02-17
id: US-PRJ-1-5
points: 2
status: done
story_id: US-PRJ-1
title: Document submodule branch tracking drift scenarios
updated: '2026-02-17'
---

Investigate and document concrete scenarios where submodule branch tracking breaks:

1. Scenario: Dev A runs `set-branch proj-x feature-1`, Dev B still has old tracking → push goes to wrong branch
2. Scenario: .gitmodules says branch=main but submodule HEAD is on a feature branch after local work
3. Scenario: `git submodule update --remote` pulls from tracked branch, overwriting local changes
4. Scenario: Submodule detached HEAD state after hub clone (default git behavior)

For each scenario: describe the trigger, what goes wrong, severity (data loss / wrong branch / confusing state), and how hard it is to recover.

Output: Failure scenarios section with severity ratings.