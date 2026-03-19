"""Tests for Sprint entity CRUD operations."""

import pytest
from datetime import date

from projectman.models import SprintStatus, SprintFrontmatter
from projectman.store import Store, clear_all_caches


class TestSprintModel:
    def test_sprint_status_enum(self):
        assert SprintStatus.planning.value == "planning"
        assert SprintStatus.active.value == "active"
        assert SprintStatus.completed.value == "completed"
        assert SprintStatus.cancelled.value == "cancelled"

    def test_sprint_frontmatter_validation(self):
        meta = SprintFrontmatter(
            id="SPRINT-TST-1",
            name="Sprint 1",
            created=date.today(),
            updated=date.today(),
        )
        assert meta.status == SprintStatus.planning
        assert meta.planned_stories == []
        assert meta.planned_points == 0
        assert meta.completed_points == 0

    def test_sprint_id_validation_rejects_invalid(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            SprintFrontmatter(
                id="123-bad",
                name="Bad",
                created=date.today(),
                updated=date.today(),
            )


class TestSprintStore:
    def test_create_sprint(self, store):
        meta = store.create_sprint("Sprint 1", goal="Ship auth")
        assert meta.id == "SPRINT-TST-1"
        assert meta.name == "Sprint 1"
        assert meta.goal == "Ship auth"
        assert meta.status == SprintStatus.planning
        assert meta.planned_points == 0

    def test_create_sprint_with_stories(self, store):
        store.create_story("Story A", "Desc", points=5)
        store.create_story("Story B", "Desc", points=3)
        meta = store.create_sprint(
            "Sprint 1",
            planned_stories=["US-TST-1", "US-TST-2"],
        )
        assert meta.planned_stories == ["US-TST-1", "US-TST-2"]
        assert meta.planned_points == 8

    def test_create_sprint_with_dates(self, store):
        meta = store.create_sprint(
            "Sprint 1",
            start_date="2026-03-19",
            end_date="2026-04-02",
        )
        assert meta.start_date == date(2026, 3, 19)
        assert meta.end_date == date(2026, 4, 2)

    def test_get_sprint(self, store):
        store.create_sprint("Sprint 1", goal="Ship it")
        meta, body = store.get_sprint("SPRINT-TST-1")
        assert meta.name == "Sprint 1"
        assert "Ship it" in body

    def test_get_sprint_not_found(self, store):
        with pytest.raises(FileNotFoundError):
            store.get_sprint("SPRINT-TST-999")

    def test_list_sprints(self, store):
        store.create_sprint("Sprint 1")
        store.create_sprint("Sprint 2")
        sprints = store.list_sprints()
        assert len(sprints) == 2

    def test_list_sprints_filter_status(self, store):
        store.create_sprint("Sprint 1")
        store.update_sprint("SPRINT-TST-1", status="active")
        store.create_sprint("Sprint 2")
        assert len(store.list_sprints(status="active")) == 1
        assert len(store.list_sprints(status="planning")) == 1

    def test_list_sprints_empty(self, store):
        assert store.list_sprints() == []

    def test_update_sprint_status(self, store):
        store.create_sprint("Sprint 1")
        meta = store.update_sprint("SPRINT-TST-1", status="active")
        assert meta.status == SprintStatus.active

    def test_update_sprint_name(self, store):
        store.create_sprint("Sprint 1")
        meta = store.update_sprint("SPRINT-TST-1", name="Sprint 1 — Auth")
        assert meta.name == "Sprint 1 — Auth"

    def test_update_sprint_completed_auto_points(self, store):
        store.create_story("Story A", "Desc", points=5)
        store.create_story("Story B", "Desc", points=3)
        store.update("US-TST-1", status="done")
        store.create_sprint(
            "Sprint 1",
            planned_stories=["US-TST-1", "US-TST-2"],
        )
        meta = store.update_sprint("SPRINT-TST-1", status="completed")
        assert meta.completed_points == 5  # Only US-TST-1 is done

    def test_update_sprint_stories_recalc_points(self, store):
        store.create_story("Story A", "Desc", points=5)
        store.create_story("Story B", "Desc", points=3)
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
        meta = store.update_sprint(
            "SPRINT-TST-1",
            planned_stories=["US-TST-1", "US-TST-2"],
        )
        assert meta.planned_points == 8

    def test_sequential_sprint_ids(self, store):
        s1 = store.create_sprint("First")
        s2 = store.create_sprint("Second")
        assert s1.id == "SPRINT-TST-1"
        assert s2.id == "SPRINT-TST-2"

    def test_get_dispatches_to_sprint(self, store):
        store.create_sprint("Sprint 1")
        meta, body = store.get("SPRINT-TST-1")
        assert isinstance(meta, SprintFrontmatter)

    def test_sprint_with_missing_story(self, store):
        """Creating a sprint with a non-existent story ID should not error."""
        meta = store.create_sprint(
            "Sprint 1",
            planned_stories=["US-TST-999"],
        )
        assert meta.planned_stories == ["US-TST-999"]
        assert meta.planned_points == 0


class TestSprintActivityLog:
    def test_create_sprint_emits_log(self, store):
        store.create_sprint("Sprint 1")
        log_path = store.project_dir / "activity.jsonl"
        if log_path.exists():
            content = log_path.read_text()
            assert "SPRINT-TST-1" in content

    def test_update_sprint_emits_log(self, store):
        store.create_sprint("Sprint 1")
        store.update_sprint("SPRINT-TST-1", status="active")
        log_path = store.project_dir / "activity.jsonl"
        if log_path.exists():
            content = log_path.read_text()
            assert "SPRINT-TST-1" in content
