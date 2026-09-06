---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-35-6
- US-PM-36-6
id: US-PM-37-5
points: 1
status: done
story_id: US-PM-37
tags: []
title: Sweep the reference docs for the removed surface and record ADR-003
updated: '2026-09-06'
---

Sweep docs/reference/mcp-tools.md, cli.md, file-formats.md, skills.md, error-paths-inventory.md, agent.md and docs/user-guide/daily-workflow.md for any project tool argument, project:<name> scope, .project/projects path, push-all, repair, validate-branches or coordinated push, and rewrite each to the prefix-routed surface (mcp-tools.md lists pm_commit and pm_push with prefix, no pm_push_all). Add ADR-003 to .project/DECISIONS.md in the existing ADR format: decision (PM data lives at projects/{name}/.project on each repo's projectman branch, the ID prefix names the store, epics are hub-level, the hub is a read-only rollup), context from the 2026-09-05 audit, alternatives considered (keep per-project data in the hub store; a private sibling repo per project; keep an optional project argument alongside the prefix; per-store epics with a hub index) and why each lost, consequences. Extend tests/test_worktree_docs.py or tests/test_docs_after_subtraction.py with a test that greps docs/ for the retired terms and asserts ADR-003 exists.