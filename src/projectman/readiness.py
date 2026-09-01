"""Task readiness checks — Definition of Ready enforcement."""

from .deps import incomplete_task_dependencies
from .models import StoryFrontmatter, TaskFrontmatter, TaskStatus
from .store import Store


def check_readiness(
    task_meta: TaskFrontmatter,
    task_body: str,
    store: Store,
    reclaim_for: str | None = None,
    *,
    stories: dict[str, StoryFrontmatter] | None = None,
    all_tasks: list[TaskFrontmatter] | None = None,
    all_stories: list[StoryFrontmatter] | None = None,
) -> dict:
    """Check if a task meets the Definition of Ready.

    reclaim_for: assignee allowed to re-claim their own task — when the task
    is already assigned to this name and is todo or in-progress, the status
    and assignee gates pass so a repeated grab is idempotent.

    stories / all_tasks / all_stories: pre-loaded context for callers that
    check many tasks at once (the board).  Without them every call re-runs
    ``get_story`` plus, for a task with dependencies, ``list_tasks`` and
    ``list_stories`` — O(n) store round-trips for an n-task board.  Single-task
    callers (pm_grab, pm_done_next) omit them and keep the store-backed path.

    ``stories`` is a *cache*, not an authority: a story id missing from it
    still falls back to ``store.get_story``.  ``list_stories`` drops archived
    stories while ``get_story`` reads them from disk, so treating a miss as
    "not found" would turn "parent story X is 'archived'" into "parent story X
    not found".  The fallback keeps the verdict byte-identical either way.

    Returns: {"ready": bool, "blockers": list[str], "warnings": list[str]}
    """
    blockers = []
    warnings = []

    reclaiming = (
        reclaim_for is not None
        and task_meta.assignee == reclaim_for
        and task_meta.status in (TaskStatus.todo, TaskStatus.in_progress)
    )

    # Hard gates
    if task_meta.archived:
        blockers.append("task is archived")
    if task_meta.status != TaskStatus.todo and not reclaiming:
        blockers.append(f"status is '{task_meta.status.value}', not 'todo'")
    if task_meta.assignee is not None and not reclaiming:
        blockers.append(f"already assigned to '{task_meta.assignee}'")
    if task_meta.points is None:
        blockers.append("no point estimate")
    if len(task_body.strip()) < 50:
        blockers.append("description too thin (<50 chars)")

    # Parent story check
    story_meta = stories.get(task_meta.story_id) if stories is not None else None
    if story_meta is None:
        try:
            story_meta, _ = store.get_story(task_meta.story_id)
        except FileNotFoundError:
            story_meta = None
            blockers.append(f"parent story {task_meta.story_id} not found")
    if story_meta is not None and story_meta.status.value not in ("active", "ready"):
        blockers.append(
            f"parent story {task_meta.story_id} is '{story_meta.status.value}'"
            " — must be 'active' or 'ready'"
        )

    # Dependency check (cross-story aware)
    if task_meta.depends_on:
        dep_tasks = all_tasks if all_tasks is not None else store.list_tasks()
        dep_stories = all_stories if all_stories is not None else store.list_stories()
        incomplete = incomplete_task_dependencies(task_meta, dep_tasks, dep_stories)
        if incomplete:
            dep_list = ", ".join(incomplete)
            blockers.append(f"incomplete dependencies: {dep_list}")

    # Soft gates (warnings only)
    #
    # Only genuinely conditional signals belong here.  Three body-structure
    # warnings ("no Implementation section", "no Testing section", "no
    # Definition of Done checklist") were removed in US-PM-4-6: they fired on
    # 100.00% of payloads across a 3,527-call corpus, so they carried zero
    # information while costing ~131 bytes on every pm_grab.  They demanded a
    # layout no generator in ProjectMan produces — create_task writes the
    # caller's description verbatim, and the only template defining that
    # layout (templates/task.md.j2) was dead code, now deleted.  They were
    # also buggy: a *completed* checklist (`- [x]`) still reported "no
    # Definition of Done checklist".  See
    # docs/reference/readiness-warnings-determination.md.  Do not reinstate.
    if task_meta.points and task_meta.points > 5:
        warnings.append(f"high points ({task_meta.points}) — consider decomposing")

    return {
        "ready": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
    }


def compute_hints(task_meta: TaskFrontmatter, task_body: str) -> list[str]:
    """Compute suitability hints for board display."""
    hints = []
    body_lower = task_body.lower()

    if len(task_body.strip()) >= 200:
        hints.append("well-scoped")
    if "## implementation" in body_lower:
        hints.append("has-impl-plan")
    if "## testing" in body_lower:
        hints.append("has-test-plan")
    if "- [ ]" in task_body:
        hints.append("has-dod")
    if task_meta.points and task_meta.points <= 3:
        hints.append("quick-win")
    if any(kw in body_lower for kw in ["design", "ux", "user experience", "mockup"]):
        hints.append("needs-design")
    if any(kw in body_lower for kw in ["coordinate", "vendor", "api key", "meeting"]):
        hints.append("needs-coordination")

    return hints
