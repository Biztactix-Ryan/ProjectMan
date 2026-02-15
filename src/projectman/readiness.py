"""Task readiness checks — Definition of Ready enforcement."""

from .models import TaskFrontmatter, TaskStatus
from .store import Store


def check_readiness(
    task_meta: TaskFrontmatter, task_body: str, store: Store
) -> dict:
    """Check if a task meets the Definition of Ready.

    Returns: {"ready": bool, "blockers": list[str], "warnings": list[str]}
    """
    blockers = []
    warnings = []

    # Hard gates
    if task_meta.status != TaskStatus.todo:
        blockers.append(f"status is '{task_meta.status.value}', not 'todo'")
    if task_meta.assignee is not None:
        blockers.append(f"already assigned to '{task_meta.assignee}'")
    if task_meta.points is None:
        blockers.append("no point estimate")
    if len(task_body.strip()) < 50:
        blockers.append("description too thin (<50 chars)")

    # Parent story check
    try:
        story_meta, _ = store.get_story(task_meta.story_id)
        if story_meta.status.value not in ("active", "ready"):
            blockers.append(
                f"parent story {task_meta.story_id} is '{story_meta.status.value}'"
                " — must be 'active' or 'ready'"
            )
    except FileNotFoundError:
        blockers.append(f"parent story {task_meta.story_id} not found")

    # Soft gates (warnings only)
    if task_meta.points and task_meta.points > 5:
        warnings.append(f"high points ({task_meta.points}) — consider decomposing")
    body_lower = task_body.lower()
    if "## implementation" not in body_lower:
        warnings.append("no Implementation section in description")
    if "## testing" not in body_lower:
        warnings.append("no Testing section in description")
    if "- [ ]" not in task_body:
        warnings.append("no Definition of Done checklist")

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
