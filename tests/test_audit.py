"""Tests for audit/drift detection."""

import frontmatter
import pytest
from datetime import date, timedelta

from projectman.audit import _check_documentation, run_audit
from projectman.store import Store, clear_all_caches


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
    clear_all_caches()  # file was modified outside Store — flush stale cache
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
    clear_all_caches()  # files were modified outside Store — flush stale cache
    report = run_audit(tmp_project)
    assert "[ERROR]" in report
    assert "dependency cycle" in report.lower()


# ── US-PRJ-42: pre-loaded data must not change what the audit says ────────
#
# ``run_audit`` used to re-query the Store inside every check (three
# ``list_stories()`` calls, a ``get_story``/``get_task`` per item, a second
# ``list_tasks()`` for the cycle check).  US-PRJ-42-5 loads each collection
# once and runs all the checks against that snapshot.  The two tests below
# are the guard rails for that change: the first pins the *report* (same
# findings, same wording, same order), the second pins the *access pattern*
# so the N+1 cannot creep back in.


def _mixed_fixture(root):
    """A project with a deliberate spread of findings across the checks.

    Covers done-story-incomplete-tasks, point-mismatch, undecomposed-story,
    missing-acceptance-criteria, thin-description (story and task),
    empty-active-epic, orphaned-epic-reference, missing-implementation-tasks,
    the criteria-drift pair and done-without-evidence — plus an archived task
    that must NOT be reported as outstanding work.  Nothing here is
    time-dependent, so the expected report is stable on any day.
    """
    store = Store(root)

    # Done story that still owes an open task, over-pointed relative to its
    # tasks, and carrying one archived (i.e. abandoned) task.
    store.create_story("Done story", "A story that is done but still owes work")
    store.create_task("US-TST-1", "Open task", "This task is still open and long enough")
    store.create_task(
        "US-TST-1", "Finished task", "Completed with no evidence recorded at all", points=2
    )
    store.create_task("US-TST-1", "Abandoned task", "This task was archived and abandoned")
    # Run-stamped so done-without-evidence still fires on it: US-PM-43-6
    # counts only completions that could have carried evidence.
    store.update("US-TST-1-2", status="done", run_id="orch-test-1")
    store.update("US-TST-1", status="done", points=5)

    # Active story with nothing under it and no acceptance criteria.
    store.create_story("Undecomposed story", "An active story with nothing under it")
    store.update("US-TST-2", status="active")

    # Thin bodies, story and task.
    store.create_story("Thin story", "Hi")
    store.create_task("US-TST-3", "Thin task", "Hi")

    # Active epic nobody linked a story to.
    store.create_epic("Empty epic", "An epic with no stories at all")
    store.update("EPIC-TST-1", status="active")

    # Story whose only task is an auto-generated test task, whose criteria are
    # then rewritten behind the reconciler's back (criteria drift) and pointed
    # at an epic that does not exist.
    store.create_story(
        "Criteria story",
        "A story whose acceptance criteria have drifted from its test tasks",
        acceptance_criteria=["Alpha behaviour is verified"],
    )
    store.update("US-TST-4", status="active")

    # Direct frontmatter edits: the audit must see these, so flush the cache.
    story_path = root / ".project" / "stories" / "US-TST-4.md"
    post = frontmatter.load(str(story_path))
    post["acceptance_criteria"] = ["Zeta reporting pipeline emits totals"]
    post["epic_id"] = "EPIC-TST-99"
    story_path.write_text(frontmatter.dumps(post))

    task_path = root / ".project" / "tasks" / "US-TST-1-3.md"
    post = frontmatter.load(str(task_path))
    post["archived"] = True
    task_path.write_text(frontmatter.dumps(post))

    clear_all_caches()


def _report_shape(report: str) -> list[str]:
    """The parts of a report that must not change: counts and findings.

    The ``digest:`` line is deliberately dropped — it fingerprints the input
    tree, so it is identical for identical input but says nothing about the
    checks.
    """
    return [
        line
        for line in report.splitlines()
        if line.startswith("- [") or line.startswith("**Errors:**")
    ]


# Captured from the pre-US-PRJ-42-5 implementation on this exact fixture, so a
# mismatch means the rewrite changed what the audit says — not just how it
# reads it.  Eleven of the checks fire here; the archived task under US-TST-1
# fires none, which is the point of including it.
EXPECTED_MIXED_REPORT = [
    "**Errors:** 1 | **Warnings:** 8 | **Info:** 3",
    "- [ERROR] Story US-TST-1 is done but has 1 incomplete task(s)",
    "- [WARN] Story US-TST-2 is active but has no tasks",
    "- [INFO] Story US-TST-1 has 5pts but tasks sum to 2pts",
    "- [INFO] Story US-TST-3 has a thin description (2 chars)",
    "- [INFO] Task US-TST-3-1 has a thin description (2 chars)",
    "- [WARN] Story US-TST-2 is active but has no acceptance criteria",
    "- [WARN] Epic EPIC-TST-1 is active but has no linked stories",
    "- [WARN] Story US-TST-4 references non-existent epic EPIC-TST-99",
    "- [WARN] Story US-TST-4 has 1 test task(s) but no implementation tasks — "
    "needs scoping before sprint",
    "- [WARN] Story US-TST-4 has 1 acceptance criterion/criteria with no test "
    "task — re-apply the criteria with pm_update to reconcile",
    "- [WARN] Story US-TST-4 has 1 test task(s) quoting an acceptance criterion "
    "that no longer exists",
    "- [WARN] 1 done task(s) that could have carried evidence have none on any "
    "run-log entry — record files/tests/dod_met with the verdict (counted only "
    "where a run-log entry was written at or after this project's first "
    "evidence, or the done transition carried a run_id)",
]


def test_mixed_fixture_report_is_unchanged(tmp_project):
    """Every finding, its wording and its order survive the pre-load rewrite."""
    _mixed_fixture(tmp_project)
    report = run_audit(tmp_project)
    assert _report_shape(report) == EXPECTED_MIXED_REPORT


def test_audit_loads_each_collection_at_most_once(tmp_project, monkeypatch):
    """No N+1: one read per collection, one body read per item, per audit.

    Counts every Store entry point the checks could reach for bulk data.
    ``list_stories``/``list_tasks`` delegate to their ``_with_bodies``
    siblings, so each name is counted separately and each must stay within
    one call; ``get_story``/``get_task`` are counted per id, because a single
    pass over items is fine and a second read of the same item is the bug.
    """
    _mixed_fixture(tmp_project)

    list_calls: dict[str, int] = {}
    item_calls: dict[tuple[str, str], int] = {}

    def count_list(name):
        original = getattr(Store, name)

        def spy(self, *args, **kwargs):
            list_calls[name] = list_calls.get(name, 0) + 1
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Store, name, spy)

    def count_item(name):
        original = getattr(Store, name)

        def spy(self, item_id, *args, **kwargs):
            key = (name, item_id)
            item_calls[key] = item_calls.get(key, 0) + 1
            return original(self, item_id, *args, **kwargs)

        monkeypatch.setattr(Store, name, spy)

    for name in (
        "list_stories",
        "list_stories_with_bodies",
        "list_tasks",
        "list_tasks_with_bodies",
        "list_epics",
    ):
        count_list(name)
    for name in ("get_story", "get_task"):
        count_item(name)

    run_audit(tmp_project)

    over_listed = {n: c for n, c in list_calls.items() if c > 1}
    assert not over_listed, f"collection re-listed during one audit: {over_listed}"
    repeated = {k: c for k, c in item_calls.items() if c > 1}
    assert not repeated, f"item body read more than once during one audit: {repeated}"


def test_audit_does_not_reload_inside_checks(tmp_project, monkeypatch):
    """The stronger form: each collection is read exactly once, up front.

    ``_mixed_fixture`` has stories, tasks and epics, so every collection is
    needed; anything beyond one read means a check went back to the Store.
    """
    _mixed_fixture(tmp_project)

    calls: list[str] = []
    for name in ("list_stories_with_bodies", "list_tasks_with_bodies", "list_epics"):
        original = getattr(Store, name)

        def spy(self, *args, __name=name, __original=original, **kwargs):
            calls.append(__name)
            return __original(self, *args, **kwargs)

        monkeypatch.setattr(Store, name, spy)

    run_audit(tmp_project)

    assert sorted(calls) == [
        "list_epics",
        "list_stories_with_bodies",
        "list_tasks_with_bodies",
    ]


# ── US-PRJ-42-6: the extracted documentation helper ──────────────────────
#
# The missing/unfilled/stale trio used to be inlined in ``run_audit``; it now
# lives in ``_check_documentation``, which takes *today* as an argument so
# staleness can be exercised without touching mtimes on disk.  These call the
# helper directly — the golden report above still covers it in situ.

_DOC_FILES = {"PROJECT.md": ["## Architecture"]}


def test_check_documentation_missing_file(tmp_path):
    findings = _check_documentation(tmp_path, _DOC_FILES, date.today())

    assert len(findings) == 1
    assert findings[0]["severity"] == "error"
    assert findings[0]["check"] == "missing-documentation"
    assert findings[0]["message"] == "PROJECT.md is missing from .project/"
    assert findings[0]["items"] == ["PROJECT.md"]


def test_check_documentation_unfilled_template(tmp_path):
    """Headings, comments, rules, table rows and the footer are not content."""
    (tmp_path / "PROJECT.md").write_text(
        "# Project\n"
        "<!-- describe the architecture -->\n"
        "-->\n"
        "---\n"
        "| a | b |\n"
        "*Last reviewed: 2026-01-01*\n"
        "*Update this when the architecture changes*\n"
    )

    findings = _check_documentation(tmp_path, _DOC_FILES, date.today())

    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert findings[0]["check"] == "unfilled-documentation"
    assert findings[0]["message"] == (
        "PROJECT.md appears to be an unfilled template — needs real content"
    )


def test_check_documentation_stale_filled_doc(tmp_path):
    """A real doc whose file has not been touched in over 30 days."""
    (tmp_path / "PROJECT.md").write_text(
        "# Project\n\nWe run a Python CLI.\nIt stores items as markdown.\n"
        "Everything else is derived from those files.\n"
    )

    findings = _check_documentation(tmp_path, _DOC_FILES, date.today() + timedelta(days=45))

    assert len(findings) == 1
    assert findings[0]["severity"] == "info"
    assert findings[0]["check"] == "stale-documentation"
    assert findings[0]["message"] == "PROJECT.md hasn't been updated in 45 days"


def test_check_documentation_fresh_filled_doc_is_silent(tmp_path):
    (tmp_path / "PROJECT.md").write_text(
        "# Project\n\nWe run a Python CLI.\nIt stores items as markdown.\n"
        "Everything else is derived from those files.\n"
    )

    assert _check_documentation(tmp_path, _DOC_FILES, date.today()) == []


def test_check_documentation_boundary_is_strictly_over_30_days(tmp_path):
    """30 days is not yet stale — the check is ``> 30``, not ``>=``."""
    (tmp_path / "PROJECT.md").write_text(
        "# Project\n\nWe run a Python CLI.\nIt stores items as markdown.\n"
        "Everything else is derived from those files.\n"
    )

    assert _check_documentation(tmp_path, _DOC_FILES, date.today() + timedelta(days=30)) == []
