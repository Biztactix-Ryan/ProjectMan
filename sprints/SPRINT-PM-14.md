---
completed_points: 21
created: '2026-09-08'
end_date: '2026-09-21'
goal: 'Hub mode leaves the package and 0.9.0 ships without it. EPIC-PM-6 removes hub
  mode in dependency order: US-PM-44 (server: no prefix parameter, no hub branches)
  and US-PM-45 (web, indexer, audit) are independent and first; US-PM-46 deletes src/projectman/hub,
  the hub CLI commands, the config keys, the tmp_hub fixture and every hub test once
  nothing imports the package; US-PM-47 deletes docs/hub-mode, scrubs the docs and
  templates, and records ADR-004 superseding ADR-003 (evidence: 9 hub/changeset uses
  in 484 sessions, 71 of 97 error sites with zero traffic, no user of the ADR-003
  redesign). US-PM-42 is carried from Sprint 13 with 4 of its points already done:
  US-PM-42-8 rewrites the Unreleased hub bullets as ''Removed: hub mode'' after US-PM-47-5,
  then US-PM-42-7 cuts [0.9.0], bumps pyproject.toml, repoints the changelog compare
  link and names 0.9.0 in docs/installation.md (Upgrading section has one line of
  headroom under its 40-line test cap). Single-project behaviour is unchanged throughout:
  IDs keep their prefix, ADR-001 orphan-branch storage stays. Planned 21 of a 21-point
  velocity (about 18 of real work). Sprint 13 closed 2026-09-08 at 6/14: US-PRJ-52
  and US-PM-43 done, US-PRJ-34 archived as moot. Pre-flight: commit the Sprint 12
  + 13 tree first, reinstall the server from the tree and restart Claude Code. After
  the sprint: the user refreshes generated skills (projectman refresh-skills --keep-local),
  tags v0.9.0 and pushes. Still needing a product call, not a slot: US-PRJ-60 and
  US-PM-22.'
id: SPRINT-PM-14
name: Sprint 14 — Remove the Hub, Ship 0.9
planned_points: 21
planned_stories:
- US-PM-44
- US-PM-45
- US-PM-46
- US-PM-47
- US-PM-42
start_date: '2026-09-08'
status: completed
updated: '2026-09-08'
---

Hub mode leaves the package and 0.9.0 ships without it. EPIC-PM-6 removes hub mode in dependency order: US-PM-44 (server: no prefix parameter, no hub branches) and US-PM-45 (web, indexer, audit) are independent and first; US-PM-46 deletes src/projectman/hub, the hub CLI commands, the config keys, the tmp_hub fixture and every hub test once nothing imports the package; US-PM-47 deletes docs/hub-mode, scrubs the docs and templates, and records ADR-004 superseding ADR-003 (evidence: 9 hub/changeset uses in 484 sessions, 71 of 97 error sites with zero traffic, no user of the ADR-003 redesign). US-PM-42 is carried from Sprint 13 with 4 of its points already done: US-PM-42-8 rewrites the Unreleased hub bullets as 'Removed: hub mode' after US-PM-47-5, then US-PM-42-7 cuts [0.9.0], bumps pyproject.toml, repoints the changelog compare link and names 0.9.0 in docs/installation.md (Upgrading section has one line of headroom under its 40-line test cap). Single-project behaviour is unchanged throughout: IDs keep their prefix, ADR-001 orphan-branch storage stays. Planned 21 of a 21-point velocity (about 18 of real work). Sprint 13 closed 2026-09-08 at 6/14: US-PRJ-52 and US-PM-43 done, US-PRJ-34 archived as moot. Pre-flight: commit the Sprint 12 + 13 tree first, reinstall the server from the tree and restart Claude Code. After the sprint: the user refreshes generated skills (projectman refresh-skills --keep-local), tags v0.9.0 and pushes. Still needing a product call, not a slot: US-PRJ-60 and US-PM-22.