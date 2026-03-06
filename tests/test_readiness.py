"""Tests for task readiness checks."""

import pytest

from projectman.readiness import check_readiness, compute_hints


GOOD_BODY = """\
## Implementation

Add the login endpoint to the API router. Create a POST /login handler
that accepts email and password, validates credentials, and returns a JWT.

## Testing

Run pytest tests/test_auth.py to verify the endpoint works.

## Definition of Done

- [ ] POST /login endpoint works
- [ ] Returns JWT on success
- [ ] Returns 401 on bad credentials
- [ ] Tests pass
"""

THIN_BODY = "Do the thing."

BARE_BODY = "x" * 60  # meets length threshold but no sections


class TestCheckReadiness:
    def test_fully_ready_task(self, store):
        store.create_story("Story", "Description here")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Add login endpoint", GOOD_BODY, points=3)
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is True
        assert result["blockers"] == []

    def test_missing_points(self, store):
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Task", GOOD_BODY)
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        assert any("no point estimate" in b for b in result["blockers"])

    def test_thin_description(self, store):
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Task", THIN_BODY, points=2)
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        assert any("thin" in b for b in result["blockers"])

    def test_parent_story_backlog(self, store):
        store.create_story("Story", "Description")
        # Story is backlog by default
        store.create_task("US-TST-1", "Task", GOOD_BODY, points=3)
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        assert any("backlog" in b for b in result["blockers"])

    def test_already_assigned(self, store):
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Task", GOOD_BODY, points=3)
        store.update("US-TST-1-1", assignee="alice")
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        assert any("already assigned" in b for b in result["blockers"])

    def test_wrong_status(self, store):
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Task", GOOD_BODY, points=3)
        store.update("US-TST-1-1", status="in-progress")
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        assert any("not 'todo'" in b for b in result["blockers"])

    def test_warnings_for_missing_sections(self, store):
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Task", BARE_BODY, points=2)
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is True
        assert any("Implementation" in w for w in result["warnings"])
        assert any("Testing" in w for w in result["warnings"])
        assert any("Definition of Done" in w for w in result["warnings"])

    def test_high_points_warning(self, store):
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Task", GOOD_BODY, points=8)
        task_meta, task_body = store.get_task("US-TST-1-1")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is True
        assert any("high points" in w for w in result["warnings"])

    def test_incomplete_deps_blocker_lists_specific_ids(self, store):
        """Readiness blocker message lists specific incomplete dep IDs."""
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        # Create two prerequisite tasks
        store.create_task("US-TST-1", "Setup DB", GOOD_BODY, points=2)
        store.create_task("US-TST-1", "Create schema", GOOD_BODY, points=2)
        # Create a task that depends on both
        store.create_task(
            "US-TST-1",
            "Run migrations",
            GOOD_BODY,
            points=2,
            depends_on=["US-TST-1-1", "US-TST-1-2"],
        )
        task_meta, task_body = store.get_task("US-TST-1-3")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        dep_blocker = [b for b in result["blockers"] if "dependencies" in b]
        assert len(dep_blocker) == 1
        assert "US-TST-1-1" in dep_blocker[0]
        assert "US-TST-1-2" in dep_blocker[0]

    def test_incomplete_deps_lists_only_undone_ids(self, store):
        """Only incomplete (non-done) dep IDs appear in the blocker."""
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "First task", GOOD_BODY, points=2)
        store.create_task("US-TST-1", "Second task", GOOD_BODY, points=2)
        # Mark first dep as done
        store.update("US-TST-1-1", status="in-progress", assignee="alice")
        store.update("US-TST-1-1", status="done")
        # Create dependent task
        store.create_task(
            "US-TST-1",
            "Third task",
            GOOD_BODY,
            points=2,
            depends_on=["US-TST-1-1", "US-TST-1-2"],
        )
        task_meta, task_body = store.get_task("US-TST-1-3")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is False
        dep_blocker = [b for b in result["blockers"] if "dependencies" in b]
        assert len(dep_blocker) == 1
        # Only the incomplete dep should be listed
        assert "US-TST-1-2" in dep_blocker[0]
        assert "US-TST-1-1" not in dep_blocker[0]

    def test_all_deps_done_no_blocker(self, store):
        """No dependency blocker when all deps are done."""
        store.create_story("Story", "Description")
        store.update("US-TST-1", status="active")
        store.create_task("US-TST-1", "Dep task", GOOD_BODY, points=2)
        store.update("US-TST-1-1", status="in-progress", assignee="alice")
        store.update("US-TST-1-1", status="done")
        store.create_task(
            "US-TST-1",
            "Main task",
            GOOD_BODY,
            points=2,
            depends_on=["US-TST-1-1"],
        )
        task_meta, task_body = store.get_task("US-TST-1-2")

        result = check_readiness(task_meta, task_body, store)
        assert result["ready"] is True
        assert not any("dependencies" in b for b in result["blockers"])


class TestComputeHints:
    def test_well_scoped_task(self, store):
        store.create_story("Story", "Description")
        store.create_task("US-TST-1", "Task", GOOD_BODY, points=2)
        task_meta, task_body = store.get_task("US-TST-1-1")

        hints = compute_hints(task_meta, task_body)
        assert "has-impl-plan" in hints
        assert "has-test-plan" in hints
        assert "has-dod" in hints
        assert "quick-win" in hints

    def test_design_task(self, store):
        store.create_story("Story", "Description")
        body = "x" * 60 + "\n\nThis task requires UX design and mockup review."
        store.create_task("US-TST-1", "Design onboarding", body, points=5)
        task_meta, task_body = store.get_task("US-TST-1-1")

        hints = compute_hints(task_meta, task_body)
        assert "needs-design" in hints
        assert "quick-win" not in hints

    def test_coordination_task(self, store):
        store.create_story("Story", "Description")
        body = "x" * 60 + "\n\nCoordinate with the vendor to get the API key."
        store.create_task("US-TST-1", "Get API credentials", body, points=1)
        task_meta, task_body = store.get_task("US-TST-1-1")

        hints = compute_hints(task_meta, task_body)
        assert "needs-coordination" in hints
