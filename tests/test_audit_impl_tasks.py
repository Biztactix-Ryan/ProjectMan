"""Tests for the missing-implementation-tasks audit check."""

import pytest

from projectman.audit import run_audit
from projectman.store import Store, clear_all_caches


def test_test_only_tasks_flagged(tmp_project):
    """Story with only 'Test: ...' tasks should trigger warning."""
    store = Store(tmp_project)
    store.create_story(
        "Story", "Description",
        acceptance_criteria=["AC one", "AC two"],
    )
    store.update("US-TST-1", status="active")
    # Create only test tasks
    store.create_task("US-TST-1", "Test: verify AC one", "test desc here !!!")
    store.create_task("US-TST-1", "Test: verify AC two", "test desc here !!!")
    clear_all_caches()
    report = run_audit(tmp_project)
    assert "missing-implementation-tasks" in report or "no implementation tasks" in report.lower()


def test_mixed_tasks_not_flagged(tmp_project):
    """Story with both test and impl tasks should NOT trigger warning."""
    store = Store(tmp_project)
    store.create_story(
        "Story", "Description",
        acceptance_criteria=["AC one"],
    )
    store.update("US-TST-1", status="active")
    store.create_task("US-TST-1", "Test: verify AC one", "test desc here !!!")
    store.create_task("US-TST-1", "Implement auth flow", "impl desc here !!!")
    clear_all_caches()
    report = run_audit(tmp_project)
    assert "no implementation tasks" not in report.lower()


def test_no_tasks_not_flagged_by_impl_check(tmp_project):
    """Story with no tasks should NOT trigger this check (caught by undecomposed-story)."""
    store = Store(tmp_project)
    store.create_story("Story", "Description")
    store.update("US-TST-1", status="active")
    clear_all_caches()
    report = run_audit(tmp_project)
    # Should see undecomposed warning, not missing-implementation-tasks
    assert "no tasks" in report.lower()
    assert "no implementation tasks" not in report.lower()


def test_backlog_story_not_checked(tmp_project):
    """Backlog stories should not be checked for impl tasks."""
    store = Store(tmp_project)
    store.create_story("Story", "Description")
    store.create_task("US-TST-1", "Test: verify something", "test desc here !!!")
    clear_all_caches()
    report = run_audit(tmp_project)
    assert "no implementation tasks" not in report.lower()


def test_ready_story_with_test_only_flagged(tmp_project):
    """Ready stories with only test tasks should also be flagged."""
    store = Store(tmp_project)
    store.create_story(
        "Story", "Description",
        acceptance_criteria=["AC one"],
    )
    store.update("US-TST-1", status="ready")
    store.create_task("US-TST-1", "Test: verify AC one", "test desc here !!!")
    clear_all_caches()
    report = run_audit(tmp_project)
    assert "no implementation tasks" in report.lower()
