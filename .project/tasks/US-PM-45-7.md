---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on: []
id: US-PM-45-7
points: 1
status: done
story_id: US-PM-45
tags: []
title: Remove the hub documentation check and hub-config digest from the audit
updated: '2026-09-08'
---

In src/projectman/audit.py delete Check 11 (missing-hub-documentation, unfilled-hub-documentation, stale-hub-documentation), the hub-config mixing in compute_state_digest, and the project_dir and known_epic_ids parameters of run_audit (and their plumbing in server.py's pm_audit if US-PM-44 left a stub). Update docs/reference/mcp-tools.md and docs/user-guide/auditing.md where they list the hub checks. Remove hub cases from tests/test_audit_since_short_circuit.py and tests/test_audit_state_digest.py. Run tests/test_audit*.py and tests/test_docs_after_subtraction.py.