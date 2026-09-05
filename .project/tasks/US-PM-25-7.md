---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-25-6
id: US-PM-25-7
points: 1
status: done
story_id: US-PM-25
tags: []
title: Put the five worker safety rules into the worker prompt template
updated: '2026-09-05'
---

In the rewritten template's worker prompt block add, verbatim: (1) 'Never run git checkout, git restore, git stash, or git reset — earlier tasks' uncommitted work lives in the working tree. To undo a temporary edit, reverse it with the same edit tool.' (2) 'Never call pm_create_* or any Store write outside a tmp_path-isolated fixture.' (3) 'Edit tracked files directly with the Edit tool; do not stage code through scratchpad files.' (4) 'If you mutation-test source files they must end byte-identical — the orchestrator checks md5s.' (5) 'Tasks that touch git plumbing must never run the new command against the real repo.' Also add the orchestrator-side instruction to snapshot modified and untracked files (tar + md5) before each dispatch and to diff against it after.