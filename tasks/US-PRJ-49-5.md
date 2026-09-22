---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on: []
id: US-PRJ-49-5
points: 1
status: done
story_id: US-PRJ-49
tags: []
title: Mark pm_fix_malformed, pm_restore, pm_push and pm_push_all destructiveHint=True
updated: '2026-09-05'
---

In src/projectman/server.py flip destructiveHint to True on the ToolAnnotations for pm_fix_malformed (~line 3668, currently False), pm_restore (~3768, False), pm_push ("Push PM Changes", False) and pm_push_all ("Coordinated Push All", False). While there, review the remaining write tools and fix any that are wrong: pm_changeset_push pushes to a remote (destructive), pm_changeset_create_prs is annotated readOnlyHint=True — confirm it only generates commands after US-PRJ-47 and leave it, otherwise fix. pm_release, pm_reindex, pm_repair, pm_update_many, verdict verbs stay non-destructive. Also ensure pm_run_log has readOnlyHint=True on its single annotation (the grep shows a bare title= line). Update docs/reference/mcp-tools.md if it lists annotations.