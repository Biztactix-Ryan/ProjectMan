---
assignee: null
created: '2026-08-20'
depends_on:
- US-PM-19-7
id: US-PM-19-8
points: 2
status: todo
story_id: US-PM-19
tags: []
title: 'Add safety rails: dirty-tree and existing-branch refusal'
updated: '2026-08-20'
---

migrate-worktree must refuse to run when the working tree is dirty (clear message: commit or stash first) and refuse when a `projectman` branch already exists locally or on origin, pointing the user at `projectman attach` instead. Exit non-zero with actionable messages; no partial state left behind on refusal.