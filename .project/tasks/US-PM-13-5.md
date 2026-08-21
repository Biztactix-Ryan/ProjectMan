---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-13-5
points: 1
status: done
story_id: US-PM-13
tags: []
title: Add project context to the worker prompt template
updated: '2026-08-21'
---

pm-orchestrate's Worker Prompt Template currently inlines only story context and the DoD checklist. Workers implement code having never seen the project's architecture or security docs.

Add a pm_context call or inline its output. Watch payload size — pm_context peaked at 48,588 chars in Study C's sample, so use its max_doc_chars parameter rather than dumping everything.