"""Tests for dependency graph utilities."""

from datetime import date

import pytest

from projectman.deps import (
    CycleError,
    build_combined_dep_graph,
    build_dep_graph,
    detect_cycle,
    incomplete_dependencies,
    incomplete_story_dependencies,
    incomplete_task_dependencies,
    topological_sort,
)
from projectman.models import StoryFrontmatter, TaskFrontmatter, TaskStatus

TODAY = date.today()


def _task(
    task_id: str,
    depends_on: list[str] | None = None,
    status: str = "todo",
    story_id: str = "US-TST-1",
) -> TaskFrontmatter:
    """Helper to create a minimal TaskFrontmatter."""
    return TaskFrontmatter(
        id=task_id,
        story_id=story_id,
        title=f"Task {task_id}",
        status=status,
        depends_on=depends_on or [],
        created=TODAY,
        updated=TODAY,
    )


def _story(
    story_id: str,
    depends_on: list[str] | None = None,
    status: str = "backlog",
) -> StoryFrontmatter:
    """Helper to create a minimal StoryFrontmatter."""
    return StoryFrontmatter(
        id=story_id,
        title=f"Story {story_id}",
        status=status,
        depends_on=depends_on or [],
        created=TODAY,
        updated=TODAY,
    )


def _task_depending_on_a_story(
    task_id: str,
    depends_on: list[str],
    status: str = "todo",
    story_id: str = "US-TST-1",
) -> TaskFrontmatter:
    """A task whose ``depends_on`` names a story, built without validation.

    ``TaskFrontmatter.depends_on`` rejects story IDs since US-PRJ-50: a task
    blocks on tasks only, because a story is not a unit of work whose
    completion a task can observe.  ``deps.py`` nonetheless still resolves a
    story ID found in a task's ``depends_on`` -- see the
    ``incomplete_task_dependencies`` and ``build_combined_dep_graph``
    docstrings -- so the tests below keep that branch covered by building the
    object with ``model_construct``, which skips validators, instead of
    deleting the cases outright.  Nothing on disk can produce such a task any
    more; if that ``deps.py`` behaviour is ever dropped, delete this helper
    and its four users with it.
    """
    return TaskFrontmatter.model_construct(
        id=task_id,
        story_id=story_id,
        title=f"Task {task_id}",
        status=TaskStatus(status),
        archived=False,
        depends_on=depends_on,
        created=TODAY,
        updated=TODAY,
    )


# ── build_dep_graph ──────────────────────────────────────────────────


class TestBuildDepGraph:
    def test_empty_list(self):
        assert build_dep_graph([]) == {}

    def test_no_dependencies(self):
        tasks = [_task("US-TST-1-1"), _task("US-TST-1-2")]
        graph = build_dep_graph(tasks)
        assert graph == {"US-TST-1-1": [], "US-TST-1-2": []}

    def test_simple_chain(self):
        tasks = [
            _task("US-TST-1-1"),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-3", depends_on=["US-TST-1-2"]),
        ]
        graph = build_dep_graph(tasks)
        assert graph == {
            "US-TST-1-1": [],
            "US-TST-1-2": ["US-TST-1-1"],
            "US-TST-1-3": ["US-TST-1-2"],
        }

    def test_diamond(self):
        tasks = [
            _task("US-TST-1-1"),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-3", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-4", depends_on=["US-TST-1-2", "US-TST-1-3"]),
        ]
        graph = build_dep_graph(tasks)
        assert graph["US-TST-1-4"] == ["US-TST-1-2", "US-TST-1-3"]

    def test_drops_unknown_ids(self):
        tasks = [
            _task("US-TST-1-1", depends_on=["US-TST-9-9"]),
            _task("US-TST-1-2", depends_on=["US-TST-1-1", "US-TST-8-8"]),
        ]
        graph = build_dep_graph(tasks)
        assert graph == {"US-TST-1-1": [], "US-TST-1-2": ["US-TST-1-1"]}


# ── detect_cycle ─────────────────────────────────────────────────────


class TestDetectCycle:
    def test_no_cycle(self):
        graph = {"US-TST-1-1": [], "US-TST-1-2": ["US-TST-1-1"]}
        assert detect_cycle(graph) is None

    def test_no_cycle_diamond(self):
        graph = {
            "US-TST-1-1": [],
            "US-TST-1-2": ["US-TST-1-1"],
            "US-TST-1-3": ["US-TST-1-1"],
            "US-TST-1-4": ["US-TST-1-2", "US-TST-1-3"],
        }
        assert detect_cycle(graph) is None

    def test_no_cycle_empty(self):
        assert detect_cycle({}) is None

    def test_self_cycle(self):
        graph = {"US-TST-1-1": ["US-TST-1-1"]}
        cycle = detect_cycle(graph)
        assert cycle is not None
        assert cycle[0] == cycle[-1] == "US-TST-1-1"
        # Path format: "US-TST-1-1 -> US-TST-1-1" (at minimum)
        assert " -> ".join(cycle).count("US-TST-1-1") >= 2

    def test_two_node_cycle(self):
        graph = {"US-TST-1-1": ["US-TST-1-2"], "US-TST-1-2": ["US-TST-1-1"]}
        cycle = detect_cycle(graph)
        assert cycle is not None
        # Full path: starts and ends with the same node
        assert cycle[0] == cycle[-1]
        assert "US-TST-1-1" in cycle
        assert "US-TST-1-2" in cycle
        assert len(cycle) == 3  # e.g. [A, B, A]

    def test_three_node_cycle(self):
        graph = {
            "US-TST-1-1": ["US-TST-1-3"],
            "US-TST-1-2": ["US-TST-1-1"],
            "US-TST-1-3": ["US-TST-1-2"],
        }
        cycle = detect_cycle(graph)
        assert cycle is not None
        # Full path: starts and ends with the same node
        assert cycle[0] == cycle[-1]
        assert len(cycle) == 4  # e.g. [A, B, C, A]
        assert set(cycle[:-1]) == {"US-TST-1-1", "US-TST-1-2", "US-TST-1-3"}


# ── CycleError ───────────────────────────────────────────────────────


class TestCycleError:
    def test_is_value_error(self):
        err = CycleError(["A", "B", "A"])
        assert isinstance(err, ValueError)

    def test_stores_cycle_path(self):
        err = CycleError(["US-TST-1-1", "US-TST-1-2", "US-TST-1-1"])
        assert err.cycle == ["US-TST-1-1", "US-TST-1-2", "US-TST-1-1"]

    def test_message_contains_path(self):
        err = CycleError(["A", "B", "C", "A"])
        assert "A -> B -> C -> A" in str(err)


# ── topological_sort ─────────────────────────────────────────────────


class TestTopologicalSort:
    def test_empty_tasks(self):
        assert topological_sort([]) == []

    def test_single_task(self):
        tasks = [_task("US-TST-1-1")]
        result = topological_sort(tasks)
        assert [t.id for t in result] == ["US-TST-1-1"]

    def test_returns_task_objects(self):
        tasks = [_task("US-TST-1-1"), _task("US-TST-1-2")]
        result = topological_sort(tasks)
        assert all(isinstance(t, TaskFrontmatter) for t in result)

    def test_independent_tasks_sorted_by_id(self):
        tasks = [_task("US-TST-1-3"), _task("US-TST-1-1"), _task("US-TST-1-2")]
        result = topological_sort(tasks)
        ids = [t.id for t in result]
        assert ids == ["US-TST-1-1", "US-TST-1-2", "US-TST-1-3"]

    def test_linear_chain_ordering(self):
        tasks = [
            _task("US-TST-1-1"),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-3", depends_on=["US-TST-1-2"]),
        ]
        result = topological_sort(tasks)
        ids = [t.id for t in result]
        assert ids == ["US-TST-1-1", "US-TST-1-2", "US-TST-1-3"]

    def test_diamond_ordering(self):
        tasks = [
            _task("US-TST-1-1"),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-3", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-4", depends_on=["US-TST-1-2", "US-TST-1-3"]),
        ]
        result = topological_sort(tasks)
        ids = [t.id for t in result]
        assert ids[0] == "US-TST-1-1"
        assert ids[-1] == "US-TST-1-4"
        assert ids.index("US-TST-1-2") < ids.index("US-TST-1-4")
        assert ids.index("US-TST-1-3") < ids.index("US-TST-1-4")

    def test_cycle_raises_cycle_error(self):
        tasks = [
            _task("US-TST-1-1", depends_on=["US-TST-1-2"]),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
        ]
        with pytest.raises(CycleError):
            topological_sort(tasks)

    def test_cycle_error_has_cycle_path(self):
        tasks = [
            _task("US-TST-1-1", depends_on=["US-TST-1-2"]),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
        ]
        with pytest.raises(CycleError) as exc_info:
            topological_sort(tasks)
        assert len(exc_info.value.cycle) >= 2

    def test_self_cycle_raises(self):
        tasks = [_task("US-TST-1-1", depends_on=["US-TST-1-1"])]
        with pytest.raises(CycleError):
            topological_sort(tasks)

    def test_three_node_cycle_raises(self):
        tasks = [
            _task("US-TST-1-1", depends_on=["US-TST-1-3"]),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
            _task("US-TST-1-3", depends_on=["US-TST-1-2"]),
        ]
        with pytest.raises(CycleError):
            topological_sort(tasks)

    def test_unknown_deps_dropped_before_sort(self):
        tasks = [
            _task("US-TST-1-1", depends_on=["US-TST-9-9"]),
            _task("US-TST-1-2", depends_on=["US-TST-1-1"]),
        ]
        result = topological_sort(tasks)
        ids = [t.id for t in result]
        assert ids == ["US-TST-1-1", "US-TST-1-2"]


# ── incomplete_dependencies ──────────────────────────────────────────


class TestIncompleteDependencies:
    def test_all_done(self):
        siblings = [
            _task("US-TST-1-1", status="done"),
            _task("US-TST-1-2", status="done"),
        ]
        task = _task("US-TST-1-3", depends_on=["US-TST-1-1", "US-TST-1-2"])
        assert incomplete_dependencies(task, siblings) == []

    def test_some_incomplete(self):
        siblings = [
            _task("US-TST-1-1", status="done"),
            _task("US-TST-1-2", status="in-progress"),
        ]
        task = _task("US-TST-1-3", depends_on=["US-TST-1-1", "US-TST-1-2"])
        result = incomplete_dependencies(task, siblings)
        assert result == ["US-TST-1-2"]

    def test_unknown_dep_ignored(self):
        siblings = [_task("US-TST-1-1", status="todo")]
        task = _task("US-TST-1-2", depends_on=["US-TST-1-1", "US-TST-9-9"])
        result = incomplete_dependencies(task, siblings)
        assert result == ["US-TST-1-1"]

    def test_no_deps(self):
        siblings = [_task("US-TST-1-1")]
        task = _task("US-TST-1-2")
        assert incomplete_dependencies(task, siblings) == []



# ── Backward compatibility ───────────────────────────────────────────


class TestBackwardCompatibility:
    def test_task_without_depends_on_defaults_to_empty(self):
        task = TaskFrontmatter(
            id="US-TST-1-1",
            story_id="US-TST-1",
            title="Legacy task",
            created=TODAY,
            updated=TODAY,
        )
        assert task.depends_on == []

    def test_legacy_tasks_build_graph_with_no_edges(self):
        tasks = [_task("US-TST-1-1"), _task("US-TST-1-2"), _task("US-TST-1-3")]
        graph = build_dep_graph(tasks)
        assert graph == {"US-TST-1-1": [], "US-TST-1-2": [], "US-TST-1-3": []}

    def test_legacy_tasks_topological_sort_returns_all(self):
        tasks = [_task("US-TST-1-1"), _task("US-TST-1-2"), _task("US-TST-1-3")]
        result = topological_sort(tasks)
        assert {t.id for t in result} == {"US-TST-1-1", "US-TST-1-2", "US-TST-1-3"}

    def test_mixed_legacy_and_new_tasks(self):
        legacy = _task("US-TST-1-1")
        new_task = _task("US-TST-1-2", depends_on=["US-TST-1-1"])
        result = topological_sort([legacy, new_task])
        ids = [t.id for t in result]
        assert ids.index("US-TST-1-1") < ids.index("US-TST-1-2")


# ── build_combined_dep_graph ──────────────────────────────────────────


class TestBuildCombinedDepGraph:
    def test_empty(self):
        assert build_combined_dep_graph([], []) == {}

    def test_tasks_only(self):
        tasks = [_task("US-TST-1-1"), _task("US-TST-1-2", depends_on=["US-TST-1-1"])]
        graph = build_combined_dep_graph(tasks, [])
        assert graph == {"US-TST-1-1": [], "US-TST-1-2": ["US-TST-1-1"]}

    def test_stories_only(self):
        stories = [_story("US-TST-1"), _story("US-TST-2", depends_on=["US-TST-1"])]
        graph = build_combined_dep_graph([], stories)
        assert graph == {"US-TST-1": [], "US-TST-2": ["US-TST-1"]}

    def test_cross_story_task_dependency(self):
        """Task in story 2 depends on task in story 1."""
        tasks = [
            _task("US-TST-1-1", story_id="US-TST-1"),
            _task("US-TST-2-1", story_id="US-TST-2", depends_on=["US-TST-1-1"]),
        ]
        graph = build_combined_dep_graph(tasks, [])
        assert graph["US-TST-2-1"] == ["US-TST-1-1"]

    def test_task_depends_on_story(self):
        """A task can depend on a story being done."""
        tasks = [_task_depending_on_a_story("US-TST-1-1", ["US-TST-1"])]
        stories = [_story("US-TST-1")]
        graph = build_combined_dep_graph(tasks, stories)
        assert graph["US-TST-1-1"] == ["US-TST-1"]

    def test_story_depends_on_task(self):
        """A story can depend on a specific task being done."""
        tasks = [_task("US-TST-1-1")]
        stories = [_story("US-TST-1", depends_on=["US-TST-1-1"])]
        graph = build_combined_dep_graph(tasks, stories)
        assert graph["US-TST-1"] == ["US-TST-1-1"]

    def test_story_depends_on_story(self):
        """Story-to-story dependencies."""
        stories = [
            _story("US-TST-1"),
            _story("US-TST-2", depends_on=["US-TST-1"]),
            _story("US-TST-3", depends_on=["US-TST-1", "US-TST-2"]),
        ]
        graph = build_combined_dep_graph([], stories)
        assert graph["US-TST-1"] == []
        assert graph["US-TST-2"] == ["US-TST-1"]
        assert graph["US-TST-3"] == ["US-TST-1", "US-TST-2"]

    def test_drops_unknown_ids(self):
        tasks = [_task("US-TST-1-1", depends_on=["US-TST-9-9"])]
        stories = [_story("US-TST-1", depends_on=["US-TST-8-8"])]
        graph = build_combined_dep_graph(tasks, stories)
        assert graph["US-TST-1-1"] == []
        assert graph["US-TST-1"] == []

    def test_mixed_graph_cycle_detection(self):
        """Cycle detection works on combined graph."""
        tasks = [_task_depending_on_a_story("US-TST-1-1", ["US-TST-1"])]
        stories = [_story("US-TST-1", depends_on=["US-TST-1-1"])]
        graph = build_combined_dep_graph(tasks, stories)
        cycle = detect_cycle(graph)
        assert cycle is not None


# ── incomplete_task_dependencies ──────────────────────────────────────


class TestIncompleteTaskDependencies:
    def test_all_done(self):
        tasks = [
            _task("US-TST-1-1", status="done", story_id="US-TST-1"),
            _task("US-TST-1-2", status="done", story_id="US-TST-2"),
        ]
        stories = [_story("US-TST-1", status="done"), _story("US-TST-2", status="done")]
        task = _task_depending_on_a_story(
            "US-TST-1-3", ["US-TST-1-1", "US-TST-1-2", "US-TST-1"]
        )
        result = incomplete_task_dependencies(task, tasks, stories)
        assert result == []

    def test_cross_story_task_incomplete(self):
        """Task depends on task in another story that's not done."""
        tasks = [
            _task("US-TST-1-1", story_id="US-TST-1", status="in-progress"),
            _task("US-TST-2-1", story_id="US-TST-2", depends_on=["US-TST-1-1"]),
        ]
        result = incomplete_task_dependencies(tasks[1], tasks, [])
        assert result == ["US-TST-1-1"]

    def test_story_dependency_incomplete(self):
        """Task depends on a story that's not done."""
        tasks = [_task_depending_on_a_story("US-TST-1-1", ["US-TST-1"])]
        stories = [_story("US-TST-1", status="active")]
        result = incomplete_task_dependencies(tasks[0], tasks, stories)
        assert result == ["US-TST-1"]

    def test_story_dependency_complete(self):
        """Task depends on a story that's done."""
        tasks = [_task_depending_on_a_story("US-TST-1-1", ["US-TST-1"])]
        stories = [_story("US-TST-1", status="done")]
        result = incomplete_task_dependencies(tasks[0], tasks, stories)
        assert result == []

    def test_mixed_dependencies(self):
        """Task depends on both tasks and stories."""
        tasks = [
            _task("US-TST-1-1", status="done"),
            _task("US-TST-1-2", status="in-progress"),
            _task_depending_on_a_story(
                "US-TST-1-3",
                ["US-TST-1-1", "US-TST-1-2", "US-TST-1", "US-TST-2"],
            ),
        ]
        stories = [
            _story("US-TST-1", status="done"),
            _story("US-TST-2", status="active"),
        ]
        result = incomplete_task_dependencies(tasks[2], tasks, stories)
        assert set(result) == {"US-TST-1-2", "US-TST-2"}


# ── incomplete_story_dependencies ─────────────────────────────────────


class TestIncompleteStoryDependencies:
    def test_all_done(self):
        tasks = [_task("US-TST-1-1", status="done")]
        stories = [
            _story("US-TST-1", status="done"),
            _story("US-TST-2", depends_on=["US-TST-1", "US-TST-1-1"]),
        ]
        result = incomplete_story_dependencies(stories[1], tasks, stories)
        assert result == []

    def test_story_depends_on_incomplete_story(self):
        stories = [
            _story("US-TST-1", status="active"),
            _story("US-TST-2", depends_on=["US-TST-1"]),
        ]
        result = incomplete_story_dependencies(stories[1], [], stories)
        assert result == ["US-TST-1"]

    def test_story_depends_on_incomplete_task(self):
        tasks = [_task("US-TST-1-1", status="in-progress")]
        stories = [_story("US-TST-1", depends_on=["US-TST-1-1"])]
        result = incomplete_story_dependencies(stories[0], tasks, stories)
        assert result == ["US-TST-1-1"]

    def test_story_chain(self):
        """Story S3 depends on S2, which depends on S1."""
        stories = [
            _story("US-TST-1", status="active"),
            _story("US-TST-2", status="backlog", depends_on=["US-TST-1"]),
            _story("US-TST-3", status="backlog", depends_on=["US-TST-2"]),
        ]
        # S3's direct dependency is S2
        result = incomplete_story_dependencies(stories[2], [], stories)
        assert result == ["US-TST-2"]
