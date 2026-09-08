---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-47-5
id: US-PM-42-8
points: 2
status: done
story_id: US-PM-42
tags: []
title: 'Rewrite the Unreleased hub entries as Removed: hub mode'
updated: '2026-09-08'
---

After EPIC-PM-6 lands, rewrite the Unreleased section of CHANGELOG.md so 0.9.0 does not headline a feature it removes. Drop or fold the hub-redesign bullets (hub stores at projects/{name}/.project, the ID prefix names the store, the hub is a read-only rollup, hub-level epics, migrate-hub, the web API routes by ID prefix, hub troubleshooting guide, the cross-repo git verbs and hub dashboards Removed bullets). Add one Removed bullet 'Hub mode' that names what is gone (hub init, add-project, set-branch, sync, migrate-hub, the prefix argument on tools and web routes, hub-level epics and rollup, docs/hub-mode) and what an existing hub should do (stay on 0.8.15; each subproject works as a single project on 0.9.0). Keep the changesets and project-argument Removed bullets since 0.8.15 users still need them. Keep the Keep a Changelog style and the ~80-column wrapping; do not rename Unreleased or bump the version. Run tests/test_docs_after_subtraction.py.