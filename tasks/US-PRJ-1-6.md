---
assignee: claude
created: 2026-02-17
id: US-PRJ-1-6
points: 2
status: done
story_id: US-PRJ-1
title: Document multi-developer hub ref conflict scenarios
updated: '2026-02-17'
---

Investigate and document what happens when multiple developers push to the hub simultaneously:

1. Scenario: Dev A and Dev B both update different submodule refs → push conflict on hub
2. Scenario: Dev A and Dev B both update the SAME submodule ref → which commit wins?
3. Scenario: Dev A pushes hub, Dev B has stale hub → submodule refs revert to old commits
4. Scenario: Nightly cron sync runs while developer is mid-push

For each: describe the conflict, whether git can auto-resolve it, what the recovery path is, and whether data is lost.

Also document the hub-on-main tension: hub never branches (PM data shouldn't fork), but that means ALL submodule ref updates compete on one branch.

Output: Multi-developer conflict section with resolution paths.