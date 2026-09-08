---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-39-7
id: US-PM-39-8
points: 1
status: done
story_id: US-PM-39
tags: []
title: Docs sweep for ?project= and the ADR-003 closure line
updated: '2026-09-07'
---

grep docs/ and src/projectman/web for `?project=` and `project=` as an HTTP parameter and rewrite each mention for `prefix` (docs/reference/mcp-tools.md, docs/reference/cli.md, docs/hub-mode/*.md, web README). Append one line to ADR-003's Consequences in .project/DECISIONS.md: the web layer now routes by prefix as of US-PM-39 and the remaining-parameter caveat is closed. Edit DECISIONS.md directly as a tracked file; do not use git checkout or stash.