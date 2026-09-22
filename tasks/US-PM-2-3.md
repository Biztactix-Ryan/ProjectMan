---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-2-2
id: US-PM-2-3
points: 2
status: done
story_id: US-PM-2
tags: []
title: Raise genuine failures as real MCP errors
updated: '2026-07-29'
---

Convert the failure paths identified in the inventory so they set is_error. Config-not-found, malformed input, and constraint violations are failures. Preserve the human-readable message.