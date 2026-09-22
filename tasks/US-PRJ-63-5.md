---
assignee: claude
created: '2026-08-22'
depends_on: []
id: US-PRJ-63-5
points: 1
status: done
story_id: US-PRJ-63
tags: []
title: Create test_performance_n1.py with a call-counting Store spy and a 100-task
  fixture
updated: '2026-08-22'
---

Create tests/test_performance_n1.py. Add a fixture that builds a project with ~10 stories and 100 tasks (use pm_create_tasks-style bulk creation or direct Store writes, warm the cache), and a spy helper that wraps Store.get_task, Store.list_tasks, Store.list_stories, Store.get_story and Store.get with counters (monkeypatch or a subclass) so tests can assert how many times each was called during a server tool invocation. No assertions on the tools yet — just the fixtures, plus one smoke test that the spy counts a known call sequence correctly.

Acceptance: tests/test_performance_n1.py exists and passes; the spy fixture is reusable by other test modules.

Files: tests/test_performance_n1.py, tests/conftest.py if the fixture is shared.