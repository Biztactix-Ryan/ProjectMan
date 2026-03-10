"""Dependency graph utilities for task ordering."""

from __future__ import annotations

from collections import defaultdict, deque

from projectman.models import TaskFrontmatter


class CycleError(ValueError):
    """Raised when a dependency cycle is detected.

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
    """Return depends_on IDs whose sibling tasks are not done."""
    status_map = {t.id: t.status for t in siblings}
    return [
        dep
        for dep in task.depends_on
        if dep in status_map and status_map[dep] != "done"
    ]
