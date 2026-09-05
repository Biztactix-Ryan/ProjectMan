---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on: []
id: US-PRJ-48-5
points: 2
status: done
story_id: US-PRJ-48
tags: []
title: Add errors.py with a coded exception taxonomy
updated: '2026-09-05'
---

Context: since Sprint 1 every tool failure already reaches the caller as a real MCP error (server.py _failed() wraps into FastMCP ToolError, isError=True). What is still missing is a machine-readable error code. Create src/projectman/errors.py defining ProjectManError(code: str) and subclasses that ALSO inherit the builtin type existing callers catch, so behaviour is preserved: NotFoundError(ProjectManError, FileNotFoundError) code=not_found; ValidationError(ProjectManError, ValueError) code=invalid; ConflictError(ProjectManError, RuntimeError) code=conflict (e.g. already claimed, cycle, nothing to commit); StoreError(ProjectManError, RuntimeError) code=store. Each carries .code and .message. Re-export deps.CycleError as a ValidationError subclass if feasible without breaking tests/test_deps.py.