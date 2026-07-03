---
acceptance_criteria:
- Hub auto-rebases submodule ref updates on push conflict
- Fast-forwardable ref conflicts resolved automatically
- Non-fast-forward conflicts flagged clearly for manual resolution
- Push retried after successful rebase
- Ref update history logged for audit
created: '2026-02-16'
epic_id: EPIC-PRJ-1
id: US-PRJ-11
points: 8
priority: must
status: done
tags: []
title: Handle hub submodule ref conflicts between developers
updated: '2026-02-19'
---

As a developer on a team, I want the hub to handle submodule ref conflicts gracefully when two people update different subprojects simultaneously so that we don't lose work or corrupt hub state.

The problem: Developer A updates submodule refs for projects X and Y, pushes hub. Developer B updates refs for projects Y and Z, pushes hub — conflict on project Y's ref.

Solution approach (opinionated):
- Hub commits that only update submodule refs should auto-rebase on push failure
- If the same subproject ref was updated by both, take the newer commit (fast-forward check)
- If refs diverged (not fast-forwardable), flag for manual resolution
- Auto-retry push after rebase (with a retry limit)
- Log all ref updates for auditability

Since hub stays on main and only tracks refs + .project/ data, conflicts should be mechanical and auto-resolvable in most cases.