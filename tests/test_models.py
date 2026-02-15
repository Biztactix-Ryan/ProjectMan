"""Tests for Pydantic models."""

import pytest
from datetime import date
from pydantic import ValidationError

from projectman.models import (
    FIBONACCI_POINTS,
    StoryFrontmatter,
    TaskFrontmatter,
    ProjectConfig,
    StoryStatus,
    TaskStatus,
    Priority,
    IndexEntry,
    ProjectIndex,
)


class TestStoryFrontmatter:
    def test_valid_story(self):
        story = StoryFrontmatter(
            id="PRJ-1", title="Test", created=date.today(), updated=date.today()
        )
        assert story.id == "PRJ-1"
        assert story.status == StoryStatus.backlog
        assert story.priority == Priority.should

    def test_fibonacci_valid(self):
        for pts in FIBONACCI_POINTS:
            story = StoryFrontmatter(
                id="PRJ-1", title="Test", points=pts,
                created=date.today(), updated=date.today()
            )
            assert story.points == pts

    def test_fibonacci_invalid(self):
        with pytest.raises(ValidationError):
            StoryFrontmatter(
                id="PRJ-1", title="Test", points=4,
                created=date.today(), updated=date.today()
            )

    def test_id_pattern_valid(self):
        StoryFrontmatter(
            id="ABC-123", title="Test", created=date.today(), updated=date.today()
        )

    def test_id_user_story_prefix(self):
        story = StoryFrontmatter(
            id="US-CEO-001", title="Test", created=date.today(), updated=date.today()
        )
        assert story.id == "US-CEO-001"

    def test_id_pattern_invalid(self):
        with pytest.raises(ValidationError):
            StoryFrontmatter(
                id="123-bad", title="Test", created=date.today(), updated=date.today()
            )

    def test_none_points_valid(self):
        story = StoryFrontmatter(
            id="PRJ-1", title="Test", points=None,
            created=date.today(), updated=date.today()
        )
        assert story.points is None


class TestTaskFrontmatter:
    def test_valid_task(self):
        task = TaskFrontmatter(
            id="PRJ-1-1", story_id="PRJ-1", title="Test task",
            created=date.today(), updated=date.today()
        )
        assert task.id == "PRJ-1-1"
        assert task.status == TaskStatus.todo

    def test_task_id_pattern_invalid(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="123-bad", story_id="PRJ-1", title="Test",
                created=date.today(), updated=date.today()
            )

    def test_fibonacci_validation(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="PRJ-1-1", story_id="PRJ-1", title="Test", points=7,
                created=date.today(), updated=date.today()
            )


class TestProjectConfig:
    def test_valid_config(self):
        config = ProjectConfig(name="test", prefix="TST")
        assert config.prefix == "TST"

    def test_prefix_must_be_uppercase(self):
        with pytest.raises(ValidationError):
            ProjectConfig(name="test", prefix="tst")

    def test_prefix_must_be_alpha(self):
        with pytest.raises(ValidationError):
            ProjectConfig(name="test", prefix="T1")

    def test_defaults(self):
        config = ProjectConfig(name="test")
        assert config.prefix == "PRJ"
        assert config.hub is False
        assert config.next_story_id == 1


class TestIndexModels:
    def test_index_entry(self):
        entry = IndexEntry(id="PRJ-1", title="Test", type="story", status="backlog")
        assert entry.type == "story"

    def test_project_index(self):
        index = ProjectIndex()
        assert index.total_points == 0
        assert index.entries == []
