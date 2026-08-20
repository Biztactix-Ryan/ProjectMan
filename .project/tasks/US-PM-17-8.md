---
assignee: claude
created: '2026-07-30'
depends_on:
- US-PM-17-7
id: US-PM-17-8
points: 2
status: done
story_id: US-PM-17
tags: []
title: Add regression tests for single-write completion
updated: '2026-08-20'
---

Cover the gap that hid this: the suite's _genuinely_complete helper only models completion via in-progress. Add a sibling helper for the single-write close (store.update(id, status="done") straight from todo) and assert it is never flagged and never demoted. Exercise both paths everywhere completion is asserted, including the blocked-prior variant. Satisfies US-PM-17-1, -2 and -5.