---
acceptance_criteria:
- CHANGELOG.md has a 0.9.0 section dated the release day that covers every story closed
  in Sprints 3 to 12 grouped as Added and Changed and Removed
- The Removed subsection names changesets and the hub PR workflow and hub dashboards
  and the project argument so upgraders learn what is gone
- pyproject.toml and every other place that states the version say 0.9.0 and the version
  test suite passes
- docs/installation.md upgrade section matches the current install path and names
  0.9.0
created: '2026-09-08'
depends_on: []
epic_id: null
id: US-PM-42
points: 5
priority: must
status: done
tags:
- release
- docs
- changelog
title: 'Release 0.9.0: the changelog covers Sprints 3 to 12 and the package version
  and install docs match'
updated: '2026-09-08'
---

As a user installing ProjectMan, I want a 0.9.0 release whose changelog explains what changed since 0.8.15 so that the orphan-branch storage, the subtraction, the hub redesign and the prefix-routed tool surface are discoverable without reading git history.

State on 2026-09-08: pyproject.toml says 0.8.15 (released 2026-07-05). CHANGELOG.md has an Unreleased section covering 2026-08-19 to 2026-09-02 (Sprints 3 to 6). Nothing from Sprints 7 to 12 is in it: orphan-branch worktree storage and attach (US-PM-19, 20, 21), the subtraction epic EPIC-PM-4 (changesets and hub PR workflow removed, pm_next, store never overwrites on create, a write dirties only the item file), the hub redesign EPIC-PM-5 (PM data at projects/{name}/.project, the project argument dropped from every tool, hub is a read-only rollup, hub-level epics), and Sprint 12 (web API routes by prefix, dashboards.py removed, search skips malformed files, hub troubleshooting guide). Six epics carry the v0.9 tag.

Scope: extend the Unreleased section to cover through Sprint 12 with Added, Changed and Removed subsections, then cut it as [0.9.0] dated the release day. Bump the version in pyproject.toml (and any place that mirrors it). Confirm docs/installation.md upgrade path still matches how the package is installed (pipx install --force from the tree, then refresh-skills --keep-local). Tagging and pushing stay with the user.