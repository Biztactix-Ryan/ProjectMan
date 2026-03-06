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

    def test_tags_default_empty_list(self):
        task = TaskFrontmatter(
            id="PRJ-1-1", story_id="PRJ-1", title="Test task",
            created=date.today(), updated=date.today()
        )
        assert task.tags == []
        assert isinstance(task.tags, list)

    def test_tags_with_values(self):
        task = TaskFrontmatter(
            id="PRJ-1-1", story_id="PRJ-1", title="Test task",
            tags=["API", "Backend"],
            created=date.today(), updated=date.today()
        )
        assert task.tags == ["API", "Backend"]

    def test_depends_on_default_empty_list(self):
        task = TaskFrontmatter(
            id="PRJ-1-1", story_id="PRJ-1", title="Test task",
            created=date.today(), updated=date.today()
        )
        assert task.depends_on == []
        assert isinstance(task.depends_on, list)

    def test_depends_on_with_values(self):
        task = TaskFrontmatter(
            id="PRJ-1-1", story_id="PRJ-1", title="Test task",
            depends_on=["PRJ-1-2", "PRJ-1-3"],
            created=date.today(), updated=date.today()
        )
        assert task.depends_on == ["PRJ-1-2", "PRJ-1-3"]

    def test_depends_on_valid_task_ids(self):
        task = TaskFrontmatter(
            id="PRJ-1-1", story_id="PRJ-1", title="Test task",
            depends_on=["US-CEO-1-1", "ABC-2-3"],
            created=date.today(), updated=date.today()
        )
        assert task.depends_on == ["US-CEO-1-1", "ABC-2-3"]

    def test_depends_on_rejects_invalid_task_id(self):
        with pytest.raises(ValidationError, match="depends_on entries must be valid task IDs"):
            TaskFrontmatter(
                id="PRJ-1-1", story_id="PRJ-1", title="Test task",
                depends_on=["123-bad"],
                created=date.today(), updated=date.today()
            )

    def test_depends_on_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="PRJ-1-1", story_id="PRJ-1", title="Test task",
                depends_on=[""],
                created=date.today(), updated=date.today()
            )

    def test_depends_on_rejects_mixed_valid_invalid(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="PRJ-1-1", story_id="PRJ-1", title="Test task",
                depends_on=["PRJ-1-2", "123-bad"],
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
        assert config.auto_commit is False
        assert config.next_story_id == 1

    def test_auto_commit_default_false(self):
        config = ProjectConfig(name="test")
        assert config.auto_commit is False

    def test_auto_commit_enable(self):
        config = ProjectConfig(name="test", auto_commit=True)
        assert config.auto_commit is True

    def test_auto_commit_disable(self):
        config = ProjectConfig(name="test", auto_commit=False)
        assert config.auto_commit is False


class TestIndexModels:
    def test_index_entry(self):
        entry = IndexEntry(id="PRJ-1", title="Test", type="story", status="backlog")
        assert entry.type == "story"

    def test_index_entry_tags_default_empty(self):
        entry = IndexEntry(id="PRJ-1", title="Test", type="story", status="backlog")
        assert entry.tags == []
        assert isinstance(entry.tags, list)

    def test_index_entry_tags_with_values(self):
        entry = IndexEntry(
            id="PRJ-1-1", title="Task", type="task", status="todo",
            tags=["API", "Frontend"]
        )
        assert entry.tags == ["API", "Frontend"]

    def test_project_index(self):
        index = ProjectIndex()
        assert index.total_points == 0
        assert index.entries == []
