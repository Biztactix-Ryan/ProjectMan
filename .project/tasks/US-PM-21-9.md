---
assignee: null
created: '2026-08-20'
depends_on:
- US-PM-19-7
id: US-PM-21-9
points: 2
status: todo
story_id: US-PM-21
tags: []
title: Document worktree rough edges and the private sibling-repo variant
updated: '2026-08-20'
---

Add docs (README or docs/) covering: fresh clones need `projectman attach`; .project is ignored-but-precious and `git clean -fdx` won't recurse into the worktree without -ff (and must not be treated as disposable); the projectman branch is visible on public repos, with the sibling <repo>-pm private-repo variant described for that case. Cross-reference ADR-001 in DECISIONS.md.