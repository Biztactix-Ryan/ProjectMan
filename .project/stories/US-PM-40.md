---
acceptance_criteria:
- pm_search over a store containing one file with unparseable frontmatter returns
  results from every other file
- The pm_search response and the /api/search payload carry a skipped count that is
  0 when every file parsed
created: '2026-09-06'
depends_on: []
epic_id: null
id: US-PM-40
points: 1
priority: should
status: done
tags:
- search
- robustness
title: Keyword search skips a malformed item file instead of aborting
updated: '2026-09-07'
---

As an agent calling pm_search, I want one item file with broken frontmatter to cost me that one file and not the whole search, so that a single bad edit in a 600-task store does not make search unusable. keyword_search in src/projectman/search.py calls frontmatter.load on every .md under epics, stories and tasks with no error handling, so one unparseable file raises out of pm_search and GET /api/search. The indexer and the audit already tolerate malformed files and pm_malformed lists them; search should follow the same rule. Catch the parse failure per file, keep going, and report how many files were skipped so the caller knows the sweep was partial (a `skipped` count on the pm_search response and the /api/search payload).