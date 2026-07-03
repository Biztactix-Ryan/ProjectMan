---
assignee: claude
created: '2026-03-05'
id: US-PRJ-28-5
points: 2
status: done
story_id: US-PRJ-28
title: Convert Server._store() to return cached Store instances
updated: '2026-03-06'
---

Currently `Server._store(project)` creates a new `Store(base_dir)` on every MCP tool call. Change it to maintain a dict of Store instances keyed by project name (or base_dir). Return the same instance across calls so the in-memory cache persists for the server's lifetime. Handle the default (non-hub) case too.