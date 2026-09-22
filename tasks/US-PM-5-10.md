---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-5-10
points: 2
status: done
story_id: US-PM-5
tags: []
title: Keep flagged orphans visible and treat an unreadable run log as work
updated: '2026-07-29'
---

Two gaps found by US-PM-5-2, pinned as 2 strict xfails in tests/test_criteria_task_reconciliation.py.

GAP 1 (visibility): when ALL acceptance criteria are removed from a story, detect_criteria_drift short-circuits on its empty-criteria guard and pm_audit Check 17 skips the story entirely. A flagged orphan is therefore never surfaced again: the flag dies with the pm_update response. Reproduced: flagged_task_ids is set on the response, yet drift returns empty and the audit never names the task. The flag is supposed to be the durable record that survives for a human to act on, so this defeats the point of flagging.

GAP 2 (fail-safe inverted): a wholly malformed run log parses as empty, so the task is treated as untouched and archived. This contradicts the documented rule in _orphan_work_reasons that an unreadable run log counts as work. The safe direction is to assume work exists when the evidence cannot be read.

Fix spans audit.py Check 17 (the empty-criteria guard / detect_criteria_drift short-circuit) and the run-log parsing in the orphan work-reason path.

DoD:
- The 2 xfail(strict=True) tests are converted to normal passing tests.
- A story with all criteria removed still surfaces its flagged orphans through pm_audit.
- An unreadable or malformed run log yields a work reason rather than an archive.
- Nothing is ever deleted: the non-destructive guarantee proven by the existing 167 tests must still hold.
- Full suite shows no new failures beyond the recorded baseline.