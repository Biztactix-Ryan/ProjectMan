---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-35-6
id: US-PM-35-7
points: 2
status: done
story_id: US-PM-35
tags: []
title: pm_commit and pm_push act on the one store a prefix names
updated: '2026-09-06'
---

Replace the scope parameter (hub / project:<name> / all) with an optional prefix on the pm_commit and pm_push MCP tools in server.py and on the commit and push CLI commands in cli.py (drop --projects and --dry-run from push). Resolution uses _hub_entry_for_prefix: omitted in a hub means the hub's own store; a prefix names one subproject store, read via hub.stores.attached_store_path; outside a hub the prefix is ignored. registry.pm_commit shrinks to: stage and commit inside that store directory only (git runs in the store dir so a worktree store commits on its projectman branch), rebuild that store's indexes, return commit_hash / message / files_committed / on_branch or nothing_to_commit. registry.pm_push shrinks to: push that store's branch with worktree.push_branch (projectman branch for a worktree store, the checked-out branch for a plain directory), refusing with a coded error when the store is not attached or has no remote. Update docs/reference/mcp-tools.md and cli.md entries for the two verbs. Tests: extend tests/test_worktree_git_ops.py or add tests/test_hub_commit_push_prefix.py with a hub fixture that has two attached subproject stores (see tests/test_add_project_worktree.py for the fixture): commit with prefix lands on that submodule's projectman branch and leaves the other store and the hub untouched; push updates the submodule's origin projectman branch; unknown prefix is not_found.