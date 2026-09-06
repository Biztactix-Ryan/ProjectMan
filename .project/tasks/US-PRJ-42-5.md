---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PRJ-42-5
points: 2
status: done
story_id: US-PRJ-42
tags: []
title: Pre-load stories, tasks, epics and bodies once and run every audit check against
  them
updated: '2026-09-06'
---

In src/projectman/audit.py run_audit, after the digest short-circuit, load all_stories = store.list_stories(), all_tasks = store.list_tasks(), all_epics = store.list_epics() once and build tasks_by_story, stories_by_epic and status-filtered views from them. Read each story and task body once (a single get_story/get_task pass or the store's cached read) into a dict for checks 5 (thin description) and the criteria/evidence checks. Rewrite every check (1 through 15, including check_completions_without_evidence and check 14 which currently reloads both lists) to use the pre-loaded data; no store.list_* or store.get_* call may sit inside a per-item loop. The report must be byte-identical for the same input: add a regression test in tests/test_audit.py that captures run_audit output on a fixture project before and after (or compares against the committed DRIFT.md rendering rules) and a call-count test that wraps Store.list_stories, list_tasks, list_epics, get_story and get_task with a counting spy and asserts each is called at most once per audit (get_* at most once per item).