---
acceptance_criteria:
- After a pm_update on a clean tree git status shows only the item file and activity.jsonl
- pm_reindex and pm_commit and the CLI reindex command regenerate all five index files
- No reader of index.yaml serves stale data after a write that skipped reindexing
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-29
points: 5
priority: should
status: done
tags:
- store
- indexer
- subtraction
title: A write leaves only the item file and the activity log dirty
updated: '2026-09-06'
---

As a developer, I want .project to stop showing five regenerated index files as modified after every single pm call so that git status on this repo means something and pm_commit commits the change I made rather than a re-render of everything.

Audit finding: `indexer.write_index` is called from 19 sites in server.py after every mutating tool. Each call re-parses every epic, story and task from disk and rewrites index.yaml, INDEX.md, INDEX-EPICS.md, INDEX-STORIES.md and INDEX-TASKS.md, whether or not their content changed.

Direction: treat the indexes as derived. Rebuild them in pm_reindex, in pm_commit immediately before staging, and in the CLI reindex command; drop the per-write calls. Any reader of index.yaml (cli.py init around line 195, store.py around line 2759, the web dashboard) must either read from the Store directly or rebuild when the index is older than the newest item file. If keeping the files tracked still causes churn, gitignore them and generate on demand; decide during scoping with the numbers in hand.

Left out of the subtraction sprint for capacity; first candidate for the next one.