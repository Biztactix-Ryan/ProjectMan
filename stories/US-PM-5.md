---
acceptance_criteria:
- Editing acceptance criteria adds test tasks for new criteria
- Test tasks for removed criteria are flagged rather than silently deleted if work
  has started
- Test task title and body stay in sync with the criterion text
- pm_audit reports a finding when a story has criteria without matching test tasks
created: '2026-07-29'
depends_on: []
epic_id: EPIC-PM-1
id: US-PM-5
points: 5
priority: should
status: done
tags:
- reliability
- audit
- found-in-planning
title: Reconcile test tasks when acceptance criteria change
updated: '2026-07-29'
---

As someone editing a story, I want its auto-generated test tasks to track its acceptance criteria, so that editing criteria does not silently orphan them.

Found while planning this epic — not present in any of the four studies.

`store.py:347-356` auto-creates one test task per acceptance criterion, but only inside `create_story`. `store.update()` never reconciles them. Reproduced on US-PM-1 and US-PM-2 of this very project: a story created with criteria, then edited via pm_update, kept its original test tasks with titles and bodies quoting criteria that no longer exist, and gained no tasks for the new ones.

Compounding issue: `pm_audit` reported "Errors: 0 | Warnings: 0 | Info: 0 — No issues found. Project is clean." while that drift was present. pm_audit's stated purpose is checking for "drift, inconsistencies, stale items", and this is exactly that. This matters beyond cosmetics because pm-orchestrate/SKILL.md uses pm_audit as its systemic health check and stops the run on ERROR-level findings — a blind spot there is a blind spot in the orchestrator's safety net.

Two defects, one story: reconcile on update, and teach the audit to detect the inconsistency.