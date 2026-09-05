"""Tests for Pydantic models."""

import pytest
from datetime import date
from pydantic import ValidationError

from projectman.models import (
    EPIC_ID,
    FIBONACCI_POINTS,
    PREFIX,
    SPRINT_ID,
    STORY_ID,
    TASK_ID,
    EpicFrontmatter,
    SprintFrontmatter,
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
            id="US-PRJ-1", title="Test", created=date.today(), updated=date.today()
        )
        assert story.id == "US-PRJ-1"
        assert story.status == StoryStatus.backlog
        assert story.priority == Priority.should

    def test_fibonacci_valid(self):
        for pts in FIBONACCI_POINTS:
            story = StoryFrontmatter(
                id="US-PRJ-1", title="Test", points=pts,
                created=date.today(), updated=date.today()
            )
            assert story.points == pts

    def test_fibonacci_invalid(self):
        with pytest.raises(ValidationError):
            StoryFrontmatter(
                id="US-PRJ-1", title="Test", points=4,
                created=date.today(), updated=date.today()
            )

    def test_id_pattern_valid(self):
        StoryFrontmatter(
            id="US-ABC-123", title="Test", created=date.today(), updated=date.today()
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
            id="US-PRJ-1", title="Test", points=None,
            created=date.today(), updated=date.today()
        )
        assert story.points is None


class TestTaskFrontmatter:
    def test_valid_task(self):
        task = TaskFrontmatter(
            id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
            created=date.today(), updated=date.today()
        )
        assert task.id == "US-PRJ-1-1"
        assert task.status == TaskStatus.todo

    def test_task_id_pattern_invalid(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="123-bad", story_id="US-PRJ-1", title="Test",
                created=date.today(), updated=date.today()
            )

    def test_fibonacci_validation(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test", points=7,
                created=date.today(), updated=date.today()
            )

    def test_tags_default_empty_list(self):
        task = TaskFrontmatter(
            id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
            created=date.today(), updated=date.today()
        )
        assert task.tags == []
        assert isinstance(task.tags, list)

    def test_tags_with_values(self):
        task = TaskFrontmatter(
            id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
            tags=["API", "Backend"],
            created=date.today(), updated=date.today()
        )
        assert task.tags == ["API", "Backend"]

    def test_depends_on_default_empty_list(self):
        task = TaskFrontmatter(
            id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
            created=date.today(), updated=date.today()
        )
        assert task.depends_on == []
        assert isinstance(task.depends_on, list)

    def test_depends_on_with_values(self):
        task = TaskFrontmatter(
            id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
            depends_on=["US-PRJ-1-2", "US-PRJ-1-3"],
            created=date.today(), updated=date.today()
        )
        assert task.depends_on == ["US-PRJ-1-2", "US-PRJ-1-3"]

    def test_depends_on_valid_task_ids(self):
        task = TaskFrontmatter(
            id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
            depends_on=["US-CEO-1-1", "US-ABC-2-3"],
            created=date.today(), updated=date.today()
        )
        assert task.depends_on == ["US-CEO-1-1", "US-ABC-2-3"]

    def test_depends_on_rejects_invalid_task_id(self):
        with pytest.raises(ValidationError, match="depends_on entries must be task IDs"):
            TaskFrontmatter(
                id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
                depends_on=["123-bad"],
                created=date.today(), updated=date.today()
            )

    def test_depends_on_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
                depends_on=[""],
                created=date.today(), updated=date.today()
            )

    def test_depends_on_rejects_mixed_valid_invalid(self):
        with pytest.raises(ValidationError):
            TaskFrontmatter(
                id="US-PRJ-1-1", story_id="US-PRJ-1", title="Test task",
                depends_on=["US-PRJ-1-2", "123-bad"],
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


# ---------------------------------------------------------------------------
# Strict ID patterns (US-PRJ-50-6)
#
# The permissive ``^[A-Za-z][\w-]*$`` these replaced accepted every ID shape
# the project has ever used *and* every shape it never should — so the tests
# that matter here are the rejections, one per way a real ID goes wrong.
# ---------------------------------------------------------------------------

TODAY = date.today()


def _story(**kw):
    return StoryFrontmatter(
        **{"title": "T", "created": TODAY, "updated": TODAY, **kw}
    )


def _task(**kw):
    return TaskFrontmatter(
        **{
            "story_id": "US-PRJ-1",
            "title": "T",
            "created": TODAY,
            "updated": TODAY,
            **kw,
        }
    )


class TestIdPatternConstants:
    def test_constants_are_compiled(self):
        for pattern in (STORY_ID, TASK_ID, EPIC_ID, SPRINT_ID):
            assert hasattr(pattern, "match"), f"{pattern!r} is not compiled"

    def test_prefix_is_an_interpolatable_fragment(self):
        # PREFIX is deliberately a raw fragment, not a compiled pattern: it is
        # only ever interpolated into the anchored patterns below.
        assert isinstance(PREFIX, str)
        assert PREFIX in STORY_ID.pattern
        assert PREFIX in TASK_ID.pattern
        assert PREFIX in EPIC_ID.pattern
        assert PREFIX in SPRINT_ID.pattern

    @pytest.mark.parametrize(
        "value", ["US-PRJ-1", "US-PM-12", "US-A-9", "US-PRJ2-100"]
    )
    def test_story_id_accepts(self, value):
        assert STORY_ID.match(value)

    @pytest.mark.parametrize(
        "value",
        [
            "US-1",           # no prefix at all
            "US-prj-1",       # lowercase prefix
            "US-PRJ",         # no number
            "US-PRJ-",        # empty number
            "US-PRJ-1-1",     # that is a task
            "USPRJ-1",        # missing separator
            "EPIC-PRJ-1",     # wrong type
            "US-2PRJ-1",      # prefix may not start with a digit
            "",
        ],
    )
    def test_story_id_rejects(self, value):
        assert not STORY_ID.match(value)

    @pytest.mark.parametrize("value", ["US-PRJ-1-1", "US-PM-12-5", "US-A-1-99"])
    def test_task_id_accepts(self, value):
        assert TASK_ID.match(value)

    @pytest.mark.parametrize(
        "value",
        [
            "US-1-1",         # no prefix
            "US-PRJ-1",       # that is a story
            "US-PRJ-1-1-1",   # too many segments
            "US-PRJ--1",      # empty story number
            "US-prj-1-1",     # lowercase prefix
            "",
        ],
    )
    def test_task_id_rejects(self, value):
        assert not TASK_ID.match(value)

    @pytest.mark.parametrize("value", ["EPIC-PRJ-1", "EPIC-PM-5", "EPIC-A-10"])
    def test_epic_id_accepts(self, value):
        assert EPIC_ID.match(value)

    @pytest.mark.parametrize(
        "value",
        ["EPIC-1", "EPIC-prj-1", "EPIC-PRJ", "US-PRJ-1", "EPIC-PRJ-1-1", ""],
    )
    def test_epic_id_rejects(self, value):
        assert not EPIC_ID.match(value)

    @pytest.mark.parametrize("value", ["SPRINT-PRJ-1", "SPRINT-PM-7"])
    def test_sprint_id_accepts(self, value):
        assert SPRINT_ID.match(value)

    @pytest.mark.parametrize(
        "value",
        ["SPRINT-7", "SPRINT-pm-7", "SPRINT-PM", "US-PM-7", "SPRINT-PM-7-1", ""],
    )
    def test_sprint_id_rejects(self, value):
        assert not SPRINT_ID.match(value)


class TestStoryIdValidation:
    def test_valid_id_accepted(self):
        assert _story(id="US-PRJ-1").id == "US-PRJ-1"

    @pytest.mark.parametrize("value", ["US-1", "US-prj-1", "PRJ-1", "EPIC-PRJ-1"])
    def test_invalid_id_rejected(self, value):
        with pytest.raises(ValidationError) as exc:
            _story(id=value)
        assert STORY_ID.pattern in str(exc.value)

    def test_depends_on_accepts_stories_and_tasks(self):
        story = _story(id="US-PRJ-2", depends_on=["US-PRJ-1", "US-PRJ-1-3"])
        assert story.depends_on == ["US-PRJ-1", "US-PRJ-1-3"]

    @pytest.mark.parametrize("dep", ["US-1", "EPIC-PRJ-1", "SPRINT-PRJ-1", "junk"])
    def test_depends_on_rejects_other_shapes(self, dep):
        with pytest.raises(ValidationError) as exc:
            _story(id="US-PRJ-2", depends_on=[dep])
        message = str(exc.value)
        assert STORY_ID.pattern in message
        assert TASK_ID.pattern in message


class TestTaskIdValidation:
    def test_valid_id_accepted(self):
        assert _task(id="US-PRJ-1-1").id == "US-PRJ-1-1"

    @pytest.mark.parametrize("value", ["US-1-1", "US-PRJ-1", "PRJ-1-1", "123-bad"])
    def test_invalid_id_rejected(self, value):
        with pytest.raises(ValidationError) as exc:
            _task(id=value)
        assert TASK_ID.pattern in str(exc.value)

    def test_depends_on_accepts_tasks(self):
        task = _task(id="US-PRJ-1-2", depends_on=["US-PRJ-1-1"])
        assert task.depends_on == ["US-PRJ-1-1"]

    @pytest.mark.parametrize("dep", ["US-PRJ-1", "US-1-1", "EPIC-PRJ-1"])
    def test_depends_on_rejects_non_tasks(self, dep):
        # A story ID is rejected here even though stories may depend on tasks:
        # the dependency only ever resolves in one direction.
        with pytest.raises(ValidationError) as exc:
            _task(id="US-PRJ-1-2", depends_on=[dep])
        assert TASK_ID.pattern in str(exc.value)


class TestEpicIdValidation:
    def test_valid_id_accepted(self):
        epic = EpicFrontmatter(
            id="EPIC-PRJ-1", title="T", created=TODAY, updated=TODAY
        )
        assert epic.id == "EPIC-PRJ-1"

    @pytest.mark.parametrize("value", ["EPIC-1", "US-PRJ-1", "EPIC-prj-1"])
    def test_invalid_id_rejected(self, value):
        with pytest.raises(ValidationError) as exc:
            EpicFrontmatter(id=value, title="T", created=TODAY, updated=TODAY)
        assert EPIC_ID.pattern in str(exc.value)


class TestSprintIdValidation:
    def test_valid_id_accepted(self):
        sprint = SprintFrontmatter(
            id="SPRINT-PRJ-1", name="S", created=TODAY, updated=TODAY
        )
        assert sprint.id == "SPRINT-PRJ-1"

    @pytest.mark.parametrize("value", ["SPRINT-1", "US-PRJ-1", "SPRINT-prj-1"])
    def test_invalid_id_rejected(self, value):
        with pytest.raises(ValidationError) as exc:
            SprintFrontmatter(id=value, name="S", created=TODAY, updated=TODAY)
        assert SPRINT_ID.pattern in str(exc.value)
