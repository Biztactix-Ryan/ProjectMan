---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-5-8
points: 2
status: done
story_id: US-PM-5
tags: []
title: Fix blank and trailing-whitespace criteria breeding duplicate test tasks
updated: '2026-07-29'
---

Found by US-PM-5-3 and pinned as 6 strict xfails in tests/test_criteria_task_reconciliation.py.

DEFECT: generate_test_task_body places the criterion after a "> " prefix. For a blank or trailing-whitespace criterion, frontmatter.dumps strips the trailing whitespace, so the on-disk body no longer equals generate_test_task_body(criterion). The "> " prefix is lost entirely for a blank criterion, criterion_from_test_task_body returns None, the task becomes invisible to reconciliation, and every subsequent update creates ANOTHER duplicate task. Growth is unbounded: reproduced 1 -> 5 tasks over 4 identical update() calls.

Reachable from the MCP surface via pm_update(acceptance_criteria="Alpha,") or a criterion with a trailing space.

Fix belongs in store.py:114-147 (generate_test_task_body / criterion_from_test_task_body). The round-trip invariant to restore: criterion_from_test_task_body(read_from_disk(generate_test_task_body(c))) == c, for every c including blank and trailing-whitespace. Consider whether a blank criterion should produce a test task at all, but do not let it produce an unparseable one.

DoD:
- The 6 xfail(strict=True) tests covering this defect are converted to normal passing tests (strict xfail means they FAIL once they start passing, so they must be flipped, not left).
- The round-trip invariant holds for blank, trailing-whitespace, leading-whitespace and whitespace-only criteria.
- Repeated identical update() calls remain a true no-op: no duplicate accumulates.
- Full suite shows no new failures beyond the recorded baseline.