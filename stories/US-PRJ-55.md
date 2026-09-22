---
acceptance_criteria:
- docs/hub-mode/troubleshooting.md exists and docs/hub-mode/setup.md links to it
- Covers a subproject reported as not attached with projectman sync as the fix
- Covers migrate-hub refusing on a dirty tree and its no-op message when nothing is
  left to migrate
- Covers a submodule projectman branch with no remote and a story whose epic_id resolves
  in neither the hub nor its own store
- Names no removed command such as repair coordinated push validate-branches or changesets
created: '2026-03-09'
epic_id: EPIC-PRJ-10
id: US-PRJ-55
points: 3
priority: could
status: done
tags:
- docs
- hub
title: Add hub-mode troubleshooting guide
updated: '2026-09-07'
---

As a hub operator, I want a troubleshooting guide for the projects/{name}/.project layout so that the failures the new hub actually produces have a written answer. Re-scoped 2026-09-06: the original criteria named auto-rebase conflicts and `pm repair`, both removed in Sprints 8 and 11. The guide now covers what Sprint 10 and 11 code can report: a subproject shown as not attached in pm_status, the rollup and GET /api/status (fix: `projectman sync`, which re-attaches a missing worktree); `projectman migrate-hub` refusing on a dirty hub or subproject tree and its friendly no-op when nothing is left; a submodule whose projectman branch has no remote yet, so pm_push has nowhere to go; a story whose epic_id names an epic in neither the hub nor its own store; and a submodule pointer that is behind the store's branch after someone else pushed. Each entry is symptom, cause, fix, in that order. Link it from docs/hub-mode/setup.md and make sure no entry names a command that no longer exists (repair, coordinated push, validate-branches, changesets).