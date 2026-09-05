"""The store raises the coded taxonomy — without changing what callers see.

``tests/test_errors.py`` covers the taxonomy classes in isolation.  This file
covers the *raise sites*: it drives representative failures through a real,
``tmp_path``-isolated :class:`~projectman.store.Store` and asserts, for each
one, all three things that matter:

1. the exception is a :class:`~projectman.errors.ProjectManError`;
2. its ``.code`` is the expected machine-readable code;
3. it is *still* an instance of the builtin the caller used to catch, so
   every pre-existing ``except FileNotFoundError`` / ``except ValueError`` /
   ``except RuntimeError`` in ``server.py``, ``cli.py`` and the test suite
   keeps working.

Message text is deliberately not asserted here beyond a substring — the exact
prose is fixed by the store's own tests, and this file must not become a
second place that has to change when a message is reworded.
"""

import pytest

from projectman.errors import (
    ConflictError,
    NotFoundError,
    ProjectManError,
    StoreError,
    ValidationError,
)
from projectman.store import NothingToCommit, Store
from projectman.worktree import MigrationError


def assert_coded(excinfo, cls, builtin, code):
    """Assert the raised exception is `cls`, carries `code`, and is a `builtin`."""
    exc = excinfo.value
    assert isinstance(exc, cls)
    assert isinstance(exc, ProjectManError)
    assert exc.code == code
    # The backwards-compatibility guarantee: the builtin callers already catch.
    assert isinstance(exc, builtin)


def make_task(store, title="a task", **kwargs):
    """Create a story and one task under it, returning the task."""
    story, _auto = store.create_story("a story", "a description")
    return store.create_task(story.id, title, "a description", **kwargs)


# ── not_found ────────────────────────────────────────────────────────


class TestNotFound:
    """Missing items raise NotFoundError — still a FileNotFoundError."""

    def test_get_task_of_a_missing_id(self, store):
        with pytest.raises(NotFoundError) as excinfo:
            store.get_task("US-TST-9-9")
        assert_coded(excinfo, NotFoundError, FileNotFoundError, "not_found")
        assert "Task not found: US-TST-9-9" in str(excinfo.value)

    def test_get_story_of_a_missing_id(self, store):
        with pytest.raises(NotFoundError) as excinfo:
            store.get_story("US-TST-99")
        assert_coded(excinfo, NotFoundError, FileNotFoundError, "not_found")

    def test_get_epic_of_a_missing_id(self, store):
        with pytest.raises(NotFoundError) as excinfo:
            store.get_epic("EPIC-TST-99")
        assert_coded(excinfo, NotFoundError, FileNotFoundError, "not_found")

    def test_get_sprint_of_a_missing_id(self, store):
        with pytest.raises(NotFoundError) as excinfo:
            store.get_sprint("SPRINT-TST-99")
        assert_coded(excinfo, NotFoundError, FileNotFoundError, "not_found")

    def test_update_of_a_missing_item(self, store):
        with pytest.raises(NotFoundError) as excinfo:
            store.update("US-TST-99", status="done")
        assert_coded(excinfo, NotFoundError, FileNotFoundError, "not_found")

    def test_create_task_under_a_missing_story(self, store):
        with pytest.raises(NotFoundError) as excinfo:
            store.create_task("US-TST-99", "orphan", "a description")
        assert_coded(excinfo, NotFoundError, FileNotFoundError, "not_found")

    def test_the_old_handler_still_catches_it(self, store):
        """A pre-taxonomy caller catching the builtin is unaffected."""
        try:
            store.get_task("US-TST-9-9")
        except FileNotFoundError as exc:
            assert exc.code == "not_found"
        else:  # pragma: no cover - the call above must raise
            pytest.fail("get_task of a missing id did not raise")


# ── invalid ──────────────────────────────────────────────────────────


class TestValidation:
    """Bad caller input raises ValidationError — still a ValueError."""

    def test_unarchive_of_a_non_task(self, store):
        with pytest.raises(ValidationError) as excinfo:
            store.unarchive("US-TST-1")
        assert_coded(excinfo, ValidationError, ValueError, "invalid")
        assert "unarchive only applies to tasks" in str(excinfo.value)

    def test_a_task_that_depends_on_itself(self, store):
        task = make_task(store)
        with pytest.raises(ValidationError) as excinfo:
            store.update(task.id, depends_on=[task.id])
        assert_coded(excinfo, ValidationError, ValueError, "invalid")
        assert "cannot depend on itself" in str(excinfo.value)

    def test_a_dependency_that_does_not_exist(self, store):
        task = make_task(store)
        with pytest.raises(ValidationError) as excinfo:
            store.update(task.id, depends_on=["US-TST-9-9"])
        assert_coded(excinfo, ValidationError, ValueError, "invalid")

    def test_clearing_an_unknown_field(self, store):
        task = make_task(store)
        with pytest.raises(ValidationError) as excinfo:
            store.update(task.id, clear="not_a_field")
        assert_coded(excinfo, ValidationError, ValueError, "invalid")

    def test_a_dependency_cycle(self, store):
        """The cycle stays a ValueError: create_tasks rolls back on one."""
        story, _auto = store.create_story("a story", "a description")
        first = store.create_task(story.id, "first", "a description")
        second = store.create_task(
            story.id, "second", "a description", depends_on=[first.id]
        )
        with pytest.raises(ValidationError) as excinfo:
            store.update(first.id, depends_on=[second.id])
        assert_coded(excinfo, ValidationError, ValueError, "invalid")
        assert "Dependency cycle detected" in str(excinfo.value)

    def test_the_old_handler_still_catches_it(self, store):
        try:
            store.unarchive("US-TST-1")
        except ValueError as exc:
            assert exc.code == "invalid"
        else:  # pragma: no cover - the call above must raise
            pytest.fail("unarchive of a non-task did not raise")


# ── conflict ─────────────────────────────────────────────────────────


class TestConflict:
    """Expected negatives raise ConflictError — still a RuntimeError."""

    def test_nothing_to_commit(self, tmp_git_project, monkeypatch):
        monkeypatch.chdir(tmp_git_project)
        with pytest.raises(NothingToCommit) as excinfo:
            Store(tmp_git_project).commit_project_changes()
        assert_coded(excinfo, ConflictError, RuntimeError, "conflict")
        assert "No .project/ changes to commit" in str(excinfo.value)

    def test_nothing_to_commit_is_a_conflict_error(self):
        assert issubclass(NothingToCommit, ConflictError)
        assert issubclass(NothingToCommit, RuntimeError)
        assert NothingToCommit.code == "conflict"


# ── store ────────────────────────────────────────────────────────────


class TestStoreFailures:
    """Git and IO failures raise StoreError — still a RuntimeError."""

    def test_push_to_a_remote_that_is_not_configured(
        self, tmp_git_project, monkeypatch
    ):
        monkeypatch.chdir(tmp_git_project)
        with pytest.raises(StoreError) as excinfo:
            Store(tmp_git_project).push_project_changes(remote="nope")
        assert_coded(excinfo, StoreError, RuntimeError, "store")
        assert "not configured" in str(excinfo.value)

    def test_migration_error_is_a_store_error(self):
        """worktree.MigrationError keeps its name and gains the code."""
        assert issubclass(MigrationError, StoreError)
        assert issubclass(MigrationError, RuntimeError)
        exc = MigrationError("boom")
        assert exc.code == "store"
        assert str(exc) == "boom"

    def test_the_old_handler_still_catches_it(self, tmp_git_project, monkeypatch):
        monkeypatch.chdir(tmp_git_project)
        try:
            Store(tmp_git_project).push_project_changes(remote="nope")
        except RuntimeError as exc:
            assert exc.code == "store"
        else:  # pragma: no cover - the call above must raise
            pytest.fail("push to an unconfigured remote did not raise")
