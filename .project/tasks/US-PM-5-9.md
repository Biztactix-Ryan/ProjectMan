---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-5-8
id: US-PM-5-9
points: 2
status: done
story_id: US-PM-5
tags: []
title: Reconcile against archived test tasks so a live criterion is not duplicated
updated: '2026-07-29'
---

Found by US-PM-5-1 and pinned as 3 strict xfails in tests/test_criteria_task_reconciliation.py.

DEFECT: plan_criteria_reconciliation matches only non-archived tasks. A LIVE criterion whose test task was archived therefore falls into the "create" bucket, so any unrelated criteria edit breeds a live duplicate. Meanwhile detect_criteria_drift suppresses that same criterion via _covered_by_archived, so pm_audit reports the project clean right up until the duplicate appears.

The two sides disagree, which contradicts the agreement contract asserted in US-PM-5-7: detect_criteria_drift is supposed to be a read-only projection of plan_criteria_reconciliation, so they can never disagree. That contract is the actual invariant being violated here.

Impact is bounded at one extra task per affected criterion. Fix near _covered_by_archived in store.py.

Decide deliberately which way to resolve it and record the reasoning: either reconciliation should also see archived tasks (and unarchive or skip rather than create), or the drift check should stop suppressing. Whichever is chosen, the two must agree.

DoD:
- The 3 xfail(strict=True) tests covering this defect are converted to normal passing tests.
- A test asserts the agreement contract directly: for the same store state, detect_criteria_drift and plan_criteria_reconciliation cannot disagree about whether a criterion is covered.
- The chosen resolution is justified in the run-log note.
- Full suite shows no new failures beyond the recorded baseline.