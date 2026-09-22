---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-04'
depends_on:
- US-PRJ-49-5
id: US-PRJ-49-6
points: 1
status: done
story_id: US-PRJ-49
tags: []
title: Add a table-driven annotation test pinning every tool's hints
updated: '2026-09-05'
---

Add tests/test_tool_annotations.py using the _tool_schemas() pattern from tests/test_bulk_archive.py::test_it_is_annotated_as_destructive. Assert: every registered tool has annotations with readOnlyHint set explicitly; every non-read-only tool sets destructiveHint explicitly; and a pinned frozenset of destructive tool names equals {pm_archive, pm_archive_many, pm_fix_malformed, pm_restore, pm_push, pm_push_all, pm_changeset_push} (adjust to match the review outcome of the previous task). Any new tool added without annotations must fail this test.