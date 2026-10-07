---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-59-6
id: US-PM-59-8
points: 3
status: done
story_id: US-PM-59
tags: []
title: Guard Write and Edit against the real .project store
updated: '2026-10-07'
---

tool.call hook on Write/Edit/NotebookEdit: resolve the target with $.fs.stat(path, {resolve:true}).realPath and refuse when it lies under the real store's resolved path (worktree store included); temp fixtures and pm MCP tools unaffected. Same subagent/opt-in scoping as US-PM-59-7.