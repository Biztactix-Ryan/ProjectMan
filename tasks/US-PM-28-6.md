---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-28-5
id: US-PM-28-6
points: 1
status: done
story_id: US-PM-28
tags: []
title: Surface the note in pm_context and keep it out of the indexer and audit and
  search
updated: '2026-09-05'
---

pm_context: when read_next() returns text, put it first in the result under `next_time` (untruncated; it is short by design) and omit the key otherwise. indexer.py, audit.py, search.py and store's doc-listing code must skip NEXT.md (it has no frontmatter and must not appear as malformed). Test: with a note present pm_audit reports no malformed finding and pm_search does not return it.