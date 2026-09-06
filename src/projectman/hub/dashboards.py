"""Hub dashboards — generate markdown dashboards from rollup data."""

from pathlib import Path
from typing import Optional

from .rollup import rollup
from .stores import NOT_ATTACHED


def generate_dashboards(root: Optional[Path] = None) -> None:
    """Write burndown.md and status.md dashboards from rollup data.

    Every row the rollup produces is rendered, including the ones for
    subprojects whose store is not mounted (US-PM-31-9): they appear in the
    Projects table with a "not attached" status and again under their own
    heading with the hint that says how to fix it.  Generating dashboards is a
    read, so it never fails because a subproject has not been migrated.
    """
    from ..config import find_project_root
    root = root or find_project_root()

    dashboards_dir = root / ".project" / "dashboards"
    dashboards_dir.mkdir(parents=True, exist_ok=True)

    data = rollup(root)

    # Status dashboard
    status_lines = ["# Hub Status Dashboard\n"]
    status_lines.append(f"**Total Projects:** {len(data['projects'])}")
    status_lines.append(f"**Total Epics:** {data.get('total_epics', 0)}")
    status_lines.append(f"**Total Stories:** {data['total_stories']}")
    status_lines.append(f"**Total Tasks:** {data['total_tasks']}")
    status_lines.append(f"**Completion:** {data['completion']}\n")

    # Epic progress section
    epic_projects = [p for p in data["projects"] if p.get("status") == "active" and p.get("epics", 0) > 0]
    if epic_projects:
        status_lines.append("## Epic Progress\n")
        status_lines.append("| Project | Epics | Stories | Completion |")
        status_lines.append("|---------|-------|---------|------------|")
        for p in epic_projects:
            total = p.get("total_points", 0)
            done = p.get("completed_points", 0)
            pct = round(done / max(total, 1) * 100)
            status_lines.append(
                f"| {p['name']} | {p.get('epics', 0)} | {p.get('stories', 0)} | {pct}% |"
            )
        status_lines.append("")

    status_lines.append("## Projects\n")
    status_lines.append("| Project | Epics | Stories | Tasks | Points | Done | Status |")
    status_lines.append("|---------|-------|---------|-------|--------|------|--------|")

    for p in data["projects"]:
        if p.get("status") == "active":
            total = p.get("total_points", 0)
            done = p.get("completed_points", 0)
            status_lines.append(
                f"| {p['name']} | {p.get('epics', 0)} | {p.get('stories', 0)} | {p.get('tasks', 0)} "
                f"| {total} | {done} | active |"
            )
        else:
            status_lines.append(f"| {p['name']} | — | — | — | — | — | {p['status']} |")

    # Spell the fix out once per unattached project rather than leaving a bare
    # status word in a table cell — the hint is the actionable half.
    unattached = [p for p in data["projects"] if p.get("status") == NOT_ATTACHED]
    if unattached:
        status_lines.append("")
        status_lines.append("## Not Attached\n")
        for p in unattached:
            status_lines.append(f"- **{p['name']}** — {p.get('hint', NOT_ATTACHED)}")

    (dashboards_dir / "status.md").write_text("\n".join(status_lines) + "\n")

    # Burndown dashboard
    burndown_lines = ["# Hub Burndown Dashboard\n"]
    burndown_lines.append(f"**Total Points:** {data['total_points']}")
    burndown_lines.append(f"**Completed:** {data['completed_points']}")
    burndown_lines.append(f"**Remaining:** {data['total_points'] - data['completed_points']}")
    burndown_lines.append(f"**Completion:** {data['completion']}\n")

    burndown_lines.append("## Per-Project Burndown\n")
    for p in data["projects"]:
        if p.get("status") == "active":
            total = p.get("total_points", 0)
            done = p.get("completed_points", 0)
            remaining = total - done
            bar_len = 20
            filled = int(bar_len * done / max(total, 1))
            bar = "█" * filled + "░" * (bar_len - filled)
            burndown_lines.append(f"**{p['name']}**: [{bar}] {done}/{total} pts")
        elif p.get("status") == NOT_ATTACHED:
            burndown_lines.append(f"**{p['name']}**: {NOT_ATTACHED} — no points to burn")

    (dashboards_dir / "burndown.md").write_text("\n".join(burndown_lines) + "\n")
