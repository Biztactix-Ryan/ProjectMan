"""Dependency graph utilities for task and story ordering."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Union

from projectman.errors import ValidationError
from projectman.models import StoryFrontmatter, TaskFrontmatter, is_archived


class CycleError(ValidationError):
    """Raised when a dependency cycle is detected.

    Still a :class:`ValueError` (``ValidationError`` inherits from it), so
    every existing ``except ValueError`` / ``pytest.raises(ValueError)``
    around a cycle keeps working; it now also carries ``code="invalid"``.

    Attributes:
        cycle: List of task IDs forming the cycle path.
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        path = " -> ".join(cycle)
        super().__init__(f"Dependency cycle detected: {path}")


def build_dep_graph(
    tasks: list[TaskFrontmatter],
) -> dict[str, list[str]]:
    """Build an adjacency list from tasks' depends_on fields.

    Returns a dict mapping each task ID to the list of task IDs it
    depends on.  Unknown IDs (not present in *tasks*) are silently
    dropped from depends_on lists.
    """
    known = {t.id for t in tasks}
    graph: dict[str, list[str]] = {}
    for task in tasks:
        graph[task.id] = [dep for dep in task.depends_on if dep in known]
    return graph


def build_combined_dep_graph(
    tasks: list[TaskFrontmatter],
    stories: list[StoryFrontmatter],
) -> dict[str, list[str]]:
    """Build an adjacency list from both tasks and stories.

    Returns a dict mapping each item ID to the list of IDs it depends on.
    Supports cross-story task dependencies and story-to-story dependencies.
    Unknown IDs are silently dropped.
    """
    known = {t.id for t in tasks} | {s.id for s in stories}
    graph: dict[str, list[str]] = {}
    for task in tasks:
        graph[task.id] = [dep for dep in task.depends_on if dep in known]
    for story in stories:
        graph[story.id] = [dep for dep in story.depends_on if dep in known]
    return graph


def detect_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return a cycle path if one exists, otherwise ``None``.

    Uses DFS with WHITE (0) / GRAY (1) / BLACK (2) node coloring.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}
    parent: dict[str, str | None] = {node: None for node in graph}

    def _dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        for dep in graph[node]:
            if dep not in color:
                continue
            if color[dep] == GRAY:
                # Back edge — reconstruct cycle
                cycle = [dep, node]
                cur = node
                while cur != dep:
                    cur = parent[cur]  # type: ignore[assignment]
                    if cur is None or cur == dep:
                        break
                    cycle.append(cur)
                cycle.append(dep)
                cycle.reverse()
                return cycle
            if color[dep] == WHITE:
                parent[dep] = node
                result = _dfs(dep)
                if result is not None:
                    return result
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            result = _dfs(node)
            if result is not None:
                return result
    return None


def topological_sort(
    tasks: list[TaskFrontmatter],
) -> list[TaskFrontmatter]:
    """Return tasks in dependency order (dependencies first).

    Uses Kahn's algorithm (BFS).  Within each depth level, tasks are
    sorted by ID for stable output.  Raises :class:`CycleError` if a
    cycle is detected.
    """
    graph = build_dep_graph(tasks)
    task_map = {t.id: t for t in tasks}

    # Check for cycles first
    cycle = detect_cycle(graph)
    if cycle is not None:
        raise CycleError(cycle)

    # Kahn's algorithm
    in_degree: dict[str, int] = defaultdict(int)
    dependents: dict[str, list[str]] = defaultdict(list)

    for node in graph:
        in_degree.setdefault(node, 0)
        for dep in graph[node]:
            dependents[dep].append(node)
            in_degree[node] += 1

    queue: deque[str] = deque(
        sorted(node for node, deg in in_degree.items() if deg == 0)
    )
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in sorted(dependents[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    return [task_map[tid] for tid in result]


def incomplete_dependencies(
    task: TaskFrontmatter,
    siblings: list[TaskFrontmatter],
) -> list[str]:
    """Return depends_on IDs whose sibling tasks are not done.

    Legacy function for backward compatibility - only checks siblings.
    For cross-story dependencies, use incomplete_task_dependencies.
    """
    status_map = {t.id: t.status for t in siblings}
    archived = {t.id for t in siblings if t.archived}
    return [
        dep
        for dep in task.depends_on
        if dep in status_map and status_map[dep] != "done" and dep not in archived
    ]


def incomplete_task_dependencies(
    task: TaskFrontmatter,
    all_tasks: list[TaskFrontmatter],
    all_stories: list[StoryFrontmatter],
) -> list[str]:
    """Return depends_on IDs that are not done (cross-story aware).

    A task dependency is incomplete if:
    - It references a task that is not done
    - It references a story that is not done
    """
    status_map: dict[str, str] = {}
    for t in all_tasks:
        status_map[t.id] = t.status.value
    for s in all_stories:
        status_map[s.id] = s.status.value
    # An archived dependency will never be finished, so it must not block its
    # dependents forever.  Before archival was orthogonal to status, archiving
    # wrote "done" and released dependents as a side effect; keeping the real
    # status means the release has to be explicit.
    archived = {t.id for t in all_tasks if t.archived}
    archived |= {s.id for s in all_stories if is_archived(s)}

    return [
        dep
        for dep in task.depends_on
        if dep in status_map and status_map[dep] != "done" and dep not in archived
    ]


def incomplete_story_dependencies(
    story: StoryFrontmatter,
    all_tasks: list[TaskFrontmatter],
    all_stories: list[StoryFrontmatter],
) -> list[str]:
    """Return depends_on IDs for a story that are not done.

    A story dependency is incomplete if:
    - It references a story that is not done
    - It references a task that is not done

    Archived dependencies are abandoned and will never reach "done", so they
    are not treated as incomplete — otherwise they would block their
    dependents forever.  (Archived *stories* already drop out because
    ``list_stories`` excludes them; archived tasks need the explicit skip
    because ``list_tasks`` returns them by default.)
    """
    archived = {t.id for t in all_tasks if t.archived}
    archived |= {s.id for s in all_stories if is_archived(s)}

    status_map: dict[str, str] = {}
    for t in all_tasks:
        status_map[t.id] = t.status.value
    for s in all_stories:
        status_map[s.id] = s.status.value

    return [
        dep
        for dep in story.depends_on
        if dep in status_map and status_map[dep] != "done" and dep not in archived
    ]


def _story_of(task_id: str, task_map: dict[str, TaskFrontmatter]) -> str | None:
    """Story id owning *task_id*, or ``None`` when the id is not a known task."""
    task = task_map.get(task_id)
    return task.story_id if task is not None else None


def _stories_connected(
    left: str,
    right: str,
    task_map: dict[str, TaskFrontmatter],
    story_map: dict[str, StoryFrontmatter],
) -> bool:
    """True when a depends_on path joins two stories, in either direction.

    The story graph is walked **undirected** and transitively: A depends_on B
    and B depends_on C connects A to C, and it does not matter which end holds
    the edge — two tasks whose stories are ordered relative to each other must
    not run in parallel lanes regardless of which one comes first.

    A story's ``depends_on`` may name a task rather than a story (the same
    latitude :func:`incomplete_story_dependencies` already honours); such an
    edge is resolved to the story that owns the task, so a dependency expressed
    at task granularity still connects the two stories.
    """
    if left == right:
        return True

    adjacency: dict[str, set[str]] = defaultdict(set)
    for story in story_map.values():
        for dep in story.depends_on:
            target = dep if dep in story_map else _story_of(dep, task_map)
            if target is None or target == story.id:
                continue
            adjacency[story.id].add(target)
            adjacency[target].add(story.id)

    seen = {left}
    queue: deque[str] = deque([left])
    while queue:
        node = queue.popleft()
        for neighbour in adjacency[node]:
            if neighbour == right:
                return True
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return False


def lane_compatible(
    store,
    in_flight_id: str,
    candidate_id: str,
    *,
    tasks: list[TaskFrontmatter] | None = None,
    stories: list[StoryFrontmatter] | None = None,
) -> bool:
    """Can *candidate_id* run in a second lane beside in-flight *in_flight_id*?

    Two tasks are lane-compatible when nothing in the store orders one against
    the other.  Four rules, all of them read from the store rather than
    remembered:

    1. **Same story** — tasks of one story share a subject and usually a file
       set, and their intra-story order is exactly what ``topological_sort``
       exists to preserve.  Never compatible.
    2. **Task depends on task** — in either direction.
    3. **Task depends on the other's story** — a task's ``depends_on`` may name
       a story (see :func:`incomplete_task_dependencies`), and depending on the
       whole story includes the task in flight.
    4. **Stories connected by depends_on** — any path, either direction,
       transitively (see :func:`_stories_connected`).

    Anything else is compatible.  Note the ordering rules are structural, not
    temporal: whether the dependency is already *done* is irrelevant here,
    because the two lanes' edit sets are what must not overlap.

    Args:
        store: Store to read tasks and stories from. May be ``None`` when both
            *tasks* and *stories* are supplied.
        in_flight_id: Id of the task already claimed in the other lane.
        candidate_id: Id of the task being considered for this lane.
        tasks: Pre-read task list, to avoid a store read per candidate when
            filtering a whole board. Defaults to ``store.list_tasks()``.
        stories: Pre-read story list. Defaults to ``store.list_stories()``.

    Raises:
        ValidationError: Either id is not a task in the store. The message
            names the id, since the caller's mistake is almost always a story
            id or a typo rather than a missing task.
    """
    all_tasks = list(store.list_tasks()) if tasks is None else list(tasks)
    all_stories = list(store.list_stories()) if stories is None else list(stories)

    task_map = {t.id: t for t in all_tasks}
    if in_flight_id not in task_map:
        raise ValidationError(f"Unknown in-flight task: {in_flight_id}")
    if candidate_id not in task_map:
        raise ValidationError(f"Unknown candidate task: {candidate_id}")

    in_flight = task_map[in_flight_id]
    candidate = task_map[candidate_id]

    # Rule 1 — one story, one lane. Also covers a task compared with itself.
    if in_flight.story_id == candidate.story_id:
        return False

    # Rules 2 and 3 — a direct edge either way, at task or story granularity.
    if in_flight.depends_on and (
        candidate_id in in_flight.depends_on
        or candidate.story_id in in_flight.depends_on
    ):
        return False
    if candidate.depends_on and (
        in_flight_id in candidate.depends_on
        or in_flight.story_id in candidate.depends_on
    ):
        return False

    # Rule 4 — the stories themselves are ordered, however indirectly.
    story_map = {s.id: s for s in all_stories}
    return not _stories_connected(
        in_flight.story_id, candidate.story_id, task_map, story_map
    )
