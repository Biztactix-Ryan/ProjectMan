---
assignee: null
created: '2026-08-20'
depends_on:
- US-PM-19-7
id: US-PM-19-9
points: 2
status: todo
story_id: US-PM-19
tags: []
title: Handle remotes and document the history-preserving variant
updated: '2026-08-20'
---

When an origin remote exists, push -u the projectman branch (both at creation and after the import commit); when no remote exists, skip cleanly with an informational message. Add command help text covering the snapshot-import default and the `git filter-repo --subdirectory-filter .project` history-preserving alternative, per ADR-001.