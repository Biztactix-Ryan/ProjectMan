---
created: '2026-09-05'
id: EPIC-PM-4
points: null
priority: must
status: done
tags:
- subtraction
- quality
- audit
target_date: null
title: Subtraction — a smaller, honest ProjectMan
updated: '2026-09-06'
---

Outcome of the 2026-09-05 full audit. ProjectMan has grown to 13.5k source lines, 4:1 test-to-source, a 31KB orchestrate skill, and a hub/changeset subsystem used 9 times in 484 sessions. This epic removes what is not earning its keep, fixes the data-integrity holes the audit found in the store, makes the skills say true and consistent things, and adds the one small thing the restart workflow was missing: a note to your next session.

Success criteria: changesets and the hub PR workflow are gone from the main package; the orchestrate skill is under 9KB of instruction with its rationale in a reference doc; creating a story or task can never silently overwrite another; a pm_update leaves only the item file and activity log dirty; upgrade docs say how to reinstall from the local tree; a fresh telemetry baseline is captured after the fixes.

Out of scope here: the hub redesign (PM data living on each repo's projectman branch, dropping the project arg) — that is its own epic once this one lands.