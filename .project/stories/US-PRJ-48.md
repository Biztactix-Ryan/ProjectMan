---
acceptance_criteria:
- Specific exception types caught where appropriate (FileNotFoundError; ValueError;
  etc.)
- Error responses include error_code and message fields
- Generic catch-all still exists as fallback
- Existing error behavior preserved for backwards compatibility
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-48
points: 5
priority: should
status: backlog
tags:
- quality
- mcp
title: Add structured error responses and specific exception types
updated: '2026-03-09'
---

As an MCP client developer, I want structured error responses so that I can programmatically handle different error types. Currently all 41 MCP tools use bare except Exception with string error returns. Should use specific exception types (FileNotFoundError, ValueError, RuntimeError) and return structured dicts with error_code, message, and context.