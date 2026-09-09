---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-48-6
id: US-PM-48-7
points: 2
status: done
story_id: US-PM-48
tags: []
title: Document the validator subagent in orchestrate-design.md and skills.md
updated: '2026-09-09'
---

Add a section "The validator subagent" to docs/reference/orchestrate-design.md: why validation stays independent of the worker (trust-but-verify unchanged), why it now runs in a discarded context (measured 2026-09-09: validation Bash output, md5 lists and diff stats were the largest visible bucket of orchestrator context growth), why the report is bounded and JSON-shaped, and what a malformed verdict does. Update the section map table at the bottom of the doc and the pm-orchestrate summary in docs/reference/skills.md.