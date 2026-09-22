---
archived: true
assignee: null
created: '2026-07-29'
depends_on: []
id: US-PM-2-1
points: null
status: done
story_id: US-PM-2
tags: []
title: 'Test: Tool failures raise a real MCP error rather than returning an error
  string body;is_error is set on every failur...'
updated: '2026-08-20'
---

Verify acceptance criterion for story US-PM-2:

> Tool failures raise a real MCP error rather than returning an error string body;is_error is set on every failure path;Distinguish expected-negative results from failures so pm_grab on a not-ready task is not an error;No tool returns a body beginning with error:;Test asserts is_error for each known failure class