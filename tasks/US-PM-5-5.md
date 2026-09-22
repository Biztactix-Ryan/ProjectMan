---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-5-5
points: 3
status: done
story_id: US-PM-5
tags: []
title: Reconcile test tasks in store.update
updated: '2026-07-29'
---

store.py:347-356 generates test tasks only inside create_story. Extend update() so changing acceptance_criteria adds tasks for new criteria and keeps existing task titles and bodies in sync with their criterion text.

Reproduction: create a story with criteria, then pm_update its acceptance_criteria. The original test tasks survive quoting criteria that no longer exist, and no tasks are created for the new ones.