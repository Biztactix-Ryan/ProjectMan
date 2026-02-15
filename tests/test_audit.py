"""Tests for audit/drift detection."""

import pytest
from datetime import date, timedelta

from projectman.audit import run_audit
from projectman.store import Store


def test_clean_project(tmp_project):
    report = run_audit(tmp_project)
    assert "No issues found" in report


def test_done_story_incomplete_tasks(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    store.create_task("US-TST-1", "Task", "Desc")
    store.update("US-TST-1", status="done")
    # Story is done but task is still todo
    report = run_audit(tmp_project)
    assert "incomplete task" in report.lower()


def test_undecomposed_story(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    store.update("US-TST-1", status="active")
    report = run_audit(tmp_project)
    assert "no tasks" in report.lower()


def test_thin_description(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Hi")  # Very short description
    report = run_audit(tmp_project)
    assert "thin description" in report.lower()


def test_missing_acceptance_criteria(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    store.update("US-TST-1", status="active")
    report = run_audit(tmp_project)
    assert "no acceptance criteria" in report.lower()


def test_missing_acceptance_criteria_not_triggered_with_acs(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Desc", acceptance_criteria=["AC one"])
    store.update("US-TST-1", status="active")
    report = run_audit(tmp_project)
    assert "no acceptance criteria" not in report.lower()


def test_drift_md_written(tmp_project):
    run_audit(tmp_project)
    drift_path = tmp_project / ".project" / "DRIFT.md"
    assert drift_path.exists()
