---
completed_points: 6
created: '2026-09-08'
end_date: '2026-09-21'
goal: '0.9.0 is cut and the pre-subtraction backlog is gone: the changelog covers
  Sprints 3 to 12 and the package version matches it (US-PM-42), the last active pre-subtraction
  epic EPIC-PRJ-6 closes with parallel hub rollup done and the vector index archived
  as moot (US-PRJ-34), the activity log gets one reader and rotates (US-PRJ-52, re-scoped
  to what the code still lacks), and pm_audit on this repo reports zero warnings by
  fixing the rules rather than the data (US-PM-43). Order: US-PRJ-34, US-PRJ-52 and
  US-PM-43 are independent and can run in parallel; US-PM-42-5 and US-PM-42-6 can
  start at once; US-PM-42-7 (cut the section, bump the version) depends on all three
  code stories so the release notes include them and is the sprint''s last task. Pre-flight
  before orchestrating: commit the uncommitted Sprint 12 tree, then reinstall the
  server from the tree (pipx install --force, refresh-skills --keep-local, restart).
  Note src/projectman/__init__.py says __version__ 0.6.2 while pyproject says 0.8.15;
  US-PM-42-6 lists every such site. Planned 14 of a 21-point velocity: US-PRJ-60 (5
  pts, three new MCP tools, runs against the subtraction direction) and US-PM-22 (unscoped
  one-line stub) need a product decision, not a sprint slot. Archived at planning
  as moot: US-PRJ-35 (search is already one numpy matrix operation) and US-PRJ-59
  (both skills were rewritten in Sprint 8). Tagging v0.9.0 and pushing stay with the
  user after the sprint closes.'
id: SPRINT-PM-13
name: Sprint 13 — Ship 0.9
planned_points: 14
planned_stories:
- US-PRJ-34
- US-PRJ-52
- US-PM-43
- US-PM-42
start_date: '2026-09-08'
status: completed
updated: '2026-09-08'
---

0.9.0 is cut and the pre-subtraction backlog is gone: the changelog covers Sprints 3 to 12 and the package version matches it (US-PM-42), the last active pre-subtraction epic EPIC-PRJ-6 closes with parallel hub rollup done and the vector index archived as moot (US-PRJ-34), the activity log gets one reader and rotates (US-PRJ-52, re-scoped to what the code still lacks), and pm_audit on this repo reports zero warnings by fixing the rules rather than the data (US-PM-43). Order: US-PRJ-34, US-PRJ-52 and US-PM-43 are independent and can run in parallel; US-PM-42-5 and US-PM-42-6 can start at once; US-PM-42-7 (cut the section, bump the version) depends on all three code stories so the release notes include them and is the sprint's last task. Pre-flight before orchestrating: commit the uncommitted Sprint 12 tree, then reinstall the server from the tree (pipx install --force, refresh-skills --keep-local, restart). Note src/projectman/__init__.py says __version__ 0.6.2 while pyproject says 0.8.15; US-PM-42-6 lists every such site. Planned 14 of a 21-point velocity: US-PRJ-60 (5 pts, three new MCP tools, runs against the subtraction direction) and US-PM-22 (unscoped one-line stub) need a product decision, not a sprint slot. Archived at planning as moot: US-PRJ-35 (search is already one numpy matrix operation) and US-PRJ-59 (both skills were rewritten in Sprint 8). Tagging v0.9.0 and pushing stay with the user after the sprint closes.