---
acceptance_criteria:
- pm_get and pm_grab accept a fields parameter selecting returned keys
- A status-only verification fetch costs a small fraction of the full payload
- pm_batch_get and pm_list_sprints support a brief or projected mode
- Default behaviour is unchanged when no projection is requested
- pm-orchestrate uses projection for its validation read
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-2
id: US-PM-10
points: 5
priority: should
status: backlog
tags:
- context-cost
- orchestrator
- api-design
title: Field projection on pm_get and pm_grab
updated: '2026-07-29'
---

As an orchestrator verifying a worker's claim, I want to fetch one field cheaply, so that distrusting the worker does not cost thousands of tokens.

pm_grab and pm_get are consistently ~50% of all context returned on ~25% of calls: Study B 61%, Study D 58%, Study A 47%, Study C 46%. Per-call averages run 1,825-4,538 chars with no verbosity control.

The important framing: every study flags pm_done_next then pm_get as redundant (Study C 138 of 138 cases, Study B 140 of 150) and recommends removing it. That recommendation is wrong. SKILL.md step 16 is pm_get(task_id) to verify the worker's self-report, and the skill's core principle is "you do not trust a worker's self-report." That read is deliberate and correct. The defect is that verifying one field costs ~3,870 bytes.

So: do not remove the read, make it cheap. A fields parameter turns the trust-but-verify design from expensive into nearly free, and it scales to the parallel workers US-PM-7 unlocks.

Also apply projection to the unprojected list calls Study D identified: pm_batch_get(type="stories") returned 37,593 chars and pm_list_sprints(status="completed") returned 27,079 chars, both dumping full bodies and acceptance criteria.

One hypothesis to NOT act on: Study A proposed suppressing story_context on repeat grabs within a story. Study D tested it directly and refuted it — only 20 of 337 grabs re-send a story already seen, ~6k tokens total. Projection is the fix; dedup is not.