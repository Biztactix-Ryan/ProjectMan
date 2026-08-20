---
acceptance_criteria:
- A task completed in a single todo-to-done write is never a migration candidate
- Applying the migration cannot move a task out of done without a positive archive
  signal
- The known legacy archives in this repo are still handled or explicitly documented
  as unrecoverable
- The module docstring's safety claim matches actual behaviour
- Regression test covers single-write completion alongside the in-progress path
created: '2026-07-30'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-17
points: 5
priority: must
status: done
tags:
- reliability
- data-loss
- migrations
- found-in-review
title: Stop the archived-as-done migration from demoting genuinely completed work
updated: '2026-08-20'
---

As someone running the archived-as-done migration, I want it to leave real completed work alone, so that repairing a metrics bug cannot destroy a record of delivered work.

`find_archived_as_done` treats a done task as an old archive when its last status event changed only `status`, moved it to `done`, and came from a never-started status (`todo`/`blocked`). A task that was genuinely finished and closed in a single write — `todo -> done`, no intermediate `in-progress` — produces a byte-identical footprint and is flagged. `migrate_archived_as_done(apply=True)` then reverts it to `todo` and sets `archived: true`.

Demonstrated on a synthetic project: one task created, completed with a single `store.update(id, status="done")`, then flagged and reverted to `status=todo archived=True`.

Hit for real: a `/pm audit` pass closed four stale placeholder tasks (US-PRJ-29-2..-5) straight from todo to done. All four immediately became migration candidates, which is how this was found — they broke `TestAgainstACopyOfThisProject`. Those four are live candidates in this repo right now, so `projectman migrate-archived --apply` would silently un-complete them.

Why it went unnoticed: the suite's only model of genuine completion, `_genuinely_complete`, routes through `in-progress` first, so the single-write close was never exercised. Closing straight from todo is normal — `pm_update(id, status="done")` and `pm_done_next` on an ungrabbed task both do it.

The module docstring asserts this cannot happen: "Every one of those failure modes is biased the same way: skip rather than write. A missed archive stays a cosmetic metrics bug; a wrongly 'restored' task destroys a real record of completed work." Rule 3 rests on real edits "usually" carrying another field, which is not a safe assumption. Either the detection needs a positive archive signal, or the migration must stop writing on this shape — and the docstring's safety claim must match whatever is decided.