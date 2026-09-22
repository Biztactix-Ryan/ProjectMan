---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-42-6
points: 1
status: done
story_id: US-PM-42
tags: []
title: Verify docs/installation.md upgrade section and every version reference
updated: '2026-09-08'
---

grep the tree for 0.8.15 and for version strings (pyproject.toml, any __version__, docs, CHANGELOG links). List every place that must change on release. Check that docs/installation.md#upgrading describes the current path: pipx install --force from the tree with the [all] extra, then projectman refresh-skills --keep-local, then restart the MCP client, with the mcp<2 pin noted. Fix any drift found. Do not bump the version in this task.