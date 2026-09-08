---
created: '2026-09-08'
id: EPIC-PM-6
points: null
priority: must
status: active
tags:
- subtraction
- hub
- v0.9
target_date: null
title: Remove hub mode
updated: '2026-09-08'
---

Decided 2026-09-08: hub mode leaves the package entirely. Evidence: the 2026-09-05 audit found the hub and changeset subsystem used 9 times in 484 sessions and 71 of 97 error sites with zero observed traffic, mostly hub and web; the ADR-003 redesign (Sprints 10 to 11, 59 points) never gained a user, and its follow-on story US-PRJ-34 was archived as moot on 2026-09-08.

Scope: src/projectman/hub (registry, migrate, stores, rollup; 2,381 lines); prefix routing in server.py (24 tools carry a prefix parameter) and the web layer (web/resolve.py, ?prefix= on routes); hub branches in indexer.py (hub README, badges), audit.py (Check 11 hub docs, hub-config digest), cli.py (init --hub, add-project, set-branch, sync, migrate-hub, --project options); ProjectConfig.hub and .projects; the architecture_hub template and hub sections of the pm agent and skill templates; docs/hub-mode and hub mentions in ten other docs and README; every hub test file and the tmp_hub fixture. ADR-004 supersedes ADR-003.

Success criteria: no module under src imports projectman.hub and the directory is gone; no MCP tool or web route takes a prefix or project argument; projectman init has no --hub flag; a legacy config.yaml carrying hub or projects still loads; docs describe single-project mode only; the full suite passes; single-project behaviour is unchanged throughout (IDs keep their prefix, the orphan-branch worktree storage of ADR-001 stays).

Out of scope: the release cut itself (US-PM-42) and any replacement for cross-repo views.