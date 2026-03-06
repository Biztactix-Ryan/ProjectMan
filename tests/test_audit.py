"""Tests for audit/drift detection."""

import frontmatter
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


def test_orphaned_dependency_detected_as_warning(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Description for the story")
    store.create_task("US-TST-1", "Task A", "Description for task A")
    # Inject an orphaned depends_on reference
    path = tmp_project / ".project" / "tasks" / "US-TST-1-1.md"
    post = frontmatter.load(str(path))
    post["depends_on"] = ["US-TST-1-99"]  # non-existent sibling
    path.write_text(frontmatter.dumps(post))
    report = run_audit(tmp_project)
    assert "[WARN]" in report
    assert "does not exist" in report.lower()


def test_dependency_cycle_detected_as_error(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "Description for the story")
    # Create two tasks without dependencies first
    store.create_task("US-TST-1", "Task A", "Description for task A")
    store.create_task("US-TST-1", "Task B", "Description for task B")
    # Now inject a cycle by rewriting the files directly (bypassing store validation)
    today = date.today().isoformat()
    for task_id, deps in [("US-TST-1-1", ["US-TST-1-2"]), ("US-TST-1-2", ["US-TST-1-1"])]:
        path = tmp_project / ".project" / "tasks" / f"{task_id}.md"
        post = frontmatter.load(str(path))
        post["depends_on"] = deps
        path.write_text(frontmatter.dumps(post))
    report = run_audit(tmp_project)
    assert "[ERROR]" in report
    assert "dependency cycle" in report.lower()
