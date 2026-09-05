---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on:
- US-PRJ-48-5
id: US-PRJ-48-7
points: 2
status: done
story_id: US-PRJ-48
tags: []
title: Make _failed emit the error code on the wire with a generic fallback
updated: '2026-09-05'
---

In server.py _failed(): when exc is a ProjectManError use its .code; otherwise map builtins (FileNotFoundError->not_found, ValueError->invalid, PermissionError->permission, everything else->internal, the generic catch-all fallback). Render the ToolError text so the human message is unchanged and the code is appended as a trailing token, e.g. 'Task US-PRJ-1-9 not found [code: not_found]'. Keep the 'except Exception as e: raise _failed(e) from e' shape in every tool body — that IS the generic fallback the acceptance criteria require. Update tests in tests/test_genuine_failures_raise.py that assert exact equality on the message to assert startswith/contains, and add a test that every code in the taxonomy renders. Also give ToolError subclass (or attribute) a .code so in-process callers (orchestrator_api.py, web routes) can branch without parsing text.