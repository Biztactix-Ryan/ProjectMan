---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on: []
id: US-PRJ-58-5
points: 2
status: done
story_id: US-PRJ-58
tags: []
title: Add an _as_list normaliser and widen tags, depends_on and ids params to accept
  lists
updated: '2026-09-05'
---

In src/projectman/server.py add _as_list(value: str | list[str] | None) -> list[str] | None next to the acceptance-criteria normaliser (~line 638): a str is split on commas, a list is taken as-is, each element stripped, empties dropped, None passes through. Change the annotation to Optional[Union[str, list[str]]] and route through _as_list for: pm_create_story tags/depends_on (L1432-1434), pm_create_epic tags (L1500), pm_create_task tags/depends_on (L1722-1723), pm_update tags/depends_on/clear (L1997-1999, L1868), pm_update_many ids/tags/depends_on (L2172-2182), pm_archive_many ids (L2434), pm_get id (L778), pm_batch_get ids (L803). Comma strings must keep working exactly as before — the existing tests are the regression guard. acceptance_criteria already accepts a list; leave it alone.