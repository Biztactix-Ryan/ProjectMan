"""Project audit — drift detection and consistency checks."""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml

from .config import load_config
from .store import Store


def run_audit(root: Path) -> str:
    """Run all audit checks and generate a report. Also writes DRIFT.md."""
    store = Store(root)
    findings = []

    # Check 1: Done stories with incomplete tasks
    for story in store.list_stories(status="done"):
        tasks = store.list_tasks(story_id=story.id)
        incomplete = [t for t in tasks if t.status.value != "done"]
        if incomplete:
            findings.append({
                "severity": "error",
                "check": "done-story-incomplete-tasks",
                "message": f"Story {story.id} is done but has {len(incomplete)} incomplete task(s)",
                "items": [t.id for t in incomplete],
            })

    # Check 2: Undecomposed stories (active/ready stories with no tasks)
    for story in store.list_stories():
        if story.status.value in ("active", "ready"):
            tasks = store.list_tasks(story_id=story.id)
            if not tasks:
                findings.append({
                    "severity": "warning",
                    "check": "undecomposed-story",
                    "message": f"Story {story.id} is {story.status.value} but has no tasks",
                    "items": [story.id],
                })

    # Check 3: Stale in-progress items (>14 days)
    stale_threshold = date.today() - timedelta(days=14)
    for task in store.list_tasks(status="in-progress"):
        if task.updated < stale_threshold:
            days = (date.today() - task.updated).days
            findings.append({
                "severity": "warning",
                "check": "stale-in-progress",
                "message": f"Task {task.id} has been in-progress for {days} days",
                "items": [task.id],
            })

    # Check 4: Point mismatches (story points != sum of task points)
    for story in store.list_stories():
        if story.points:
            tasks = store.list_tasks(story_id=story.id)
            task_points = sum(t.points or 0 for t in tasks)
            if tasks and task_points > 0 and task_points != story.points:
                findings.append({
                    "severity": "info",
                    "check": "point-mismatch",
                    "message": f"Story {story.id} has {story.points}pts but tasks sum to {task_points}pts",
                    "items": [story.id],
                })

    # Check 5: Thin descriptions (body < 20 chars)
    for story in store.list_stories():
        _, body = store.get_story(story.id)
        if len(body.strip()) < 20:
            findings.append({
                "severity": "info",
                "check": "thin-description",
                "message": f"Story {story.id} has a thin description ({len(body.strip())} chars)",
                "items": [story.id],
            })

    for task in store.list_tasks():
        _, body = store.get_task(task.id)
        if len(body.strip()) < 20:
            findings.append({
                "severity": "info",
                "check": "thin-description",
                "message": f"Task {task.id} has a thin description ({len(body.strip())} chars)",
                "items": [task.id],
            })

    # Check 6: Active/ready stories missing acceptance criteria
    for story in store.list_stories():
        if story.status.value in ("active", "ready"):
            if not story.acceptance_criteria:
                findings.append({
                    "severity": "warning",
                    "check": "missing-acceptance-criteria",
                    "message": f"Story {story.id} is {story.status.value} but has no acceptance criteria",
                    "items": [story.id],
                })

    # Check 7: Documentation staleness and completeness
    doc_files = {
        "PROJECT.md": ["## Architecture", "## Key Decisions"],
        "INFRASTRUCTURE.md": ["## Environments", "## CI/CD"],
        "SECURITY.md": ["## Authentication", "## Authorization", "## Known Risks"],
    }
    for doc_name, required_sections in doc_files.items():
        doc_path = store.project_dir / doc_name
        if not doc_path.exists():
            findings.append({
                "severity": "error",
                "check": "missing-documentation",
                "message": f"{doc_name} is missing from .project/",
                "items": [doc_name],
            })
            continue

        content = doc_path.read_text()

        # Check for unfilled template (only HTML comments, no real content)
        lines = [l.strip() for l in content.splitlines()
                 if l.strip() and not l.strip().startswith("#")
                 and not l.strip().startswith("<!--")
                 and not l.strip().startswith("-->")
                 and not l.strip().startswith("*Last reviewed")
                 and not l.strip().startswith("*Update this")
                 and not l.strip().startswith("---")
                 and not l.strip().startswith("|")
                 and l.strip() != "|"]
        if len(lines) < 3:
            findings.append({
                "severity": "warning",
                "check": "unfilled-documentation",
                "message": f"{doc_name} appears to be an unfilled template — needs real content",
                "items": [doc_name],
            })

        # Check file age (>30 days since last modification)
        import os
        mtime = date.fromtimestamp(os.path.getmtime(doc_path))
        age_days = (date.today() - mtime).days
        if age_days > 30:
            findings.append({
                "severity": "info",
                "check": "stale-documentation",
                "message": f"{doc_name} hasn't been updated in {age_days} days",
                "items": [doc_name],
            })

    # Check 7: Empty active epic (active epic with no linked stories)
    for epic in store.list_epics(status="active"):
        linked = [s for s in store.list_stories() if s.epic_id == epic.id]
        if not linked:
            findings.append({
                "severity": "warning",
                "check": "empty-active-epic",
                "message": f"Epic {epic.id} is active but has no linked stories",
                "items": [epic.id],
            })

    # Check 8: Done epic with open stories
    for epic in store.list_epics(status="done"):
        linked = [s for s in store.list_stories() if s.epic_id == epic.id]
        open_stories = [s for s in linked if s.status.value not in ("done", "archived")]
        if open_stories:
            findings.append({
                "severity": "error",
                "check": "done-epic-open-stories",
                "message": f"Epic {epic.id} is done but has {len(open_stories)} open story/stories",
                "items": [s.id for s in open_stories],
            })

    # Check 9: Orphaned epic reference (story references non-existent epic_id)
    epic_ids = {e.id for e in store.list_epics()}
    for story in store.list_stories():
        if story.epic_id and story.epic_id not in epic_ids:
            findings.append({
                "severity": "warning",
                "check": "orphaned-epic-reference",
                "message": f"Story {story.id} references non-existent epic {story.epic_id}",
                "items": [story.id],
            })

    # Check 10: Stale draft epic (draft >30 days with no stories)
    draft_threshold = date.today() - timedelta(days=30)
    for epic in store.list_epics(status="draft"):
        if epic.updated < draft_threshold:
            linked = [s for s in store.list_stories() if s.epic_id == epic.id]
            if not linked:
                days = (date.today() - epic.updated).days
                findings.append({
                    "severity": "info",
                    "check": "stale-draft-epic",
                    "message": f"Epic {epic.id} has been in draft for {days} days with no stories",
                    "items": [epic.id],
                })

    # Check 11: Hub documentation checks (when hub mode)
    config = load_config(root)
    if config.hub:
        hub_docs = {
            "VISION.md": ["## Mission", "## Product Principles"],
            "ARCHITECTURE.md": ["## Overview", "## Service Map"],
            "DECISIONS.md": ["## Decisions"],
        }
        for doc_name, _sections in hub_docs.items():
            doc_path = store.project_dir / doc_name
            if not doc_path.exists():
                findings.append({
                    "severity": "warning",
                    "check": "missing-hub-documentation",
                    "message": f"{doc_name} is missing from hub .project/",
                    "items": [doc_name],
                })
                continue

            content = doc_path.read_text()
            lines = [l.strip() for l in content.splitlines()
                     if l.strip() and not l.strip().startswith("#")
                     and not l.strip().startswith("<!--")
                     and not l.strip().startswith("-->")
                     and not l.strip().startswith("---")
                     and not l.strip().startswith("|")
                     and l.strip() != "|"]
            if len(lines) < 3:
                findings.append({
                    "severity": "info",
                    "check": "unfilled-hub-documentation",
                    "message": f"{doc_name} appears to be an unfilled template — needs real content",
                    "items": [doc_name],
                })

            import os
            mtime = date.fromtimestamp(os.path.getmtime(doc_path))
            age_days = (date.today() - mtime).days
            if age_days > 30:
                findings.append({
                    "severity": "info",
                    "check": "stale-hub-documentation",
                    "message": f"{doc_name} hasn't been updated in {age_days} days",
                    "items": [doc_name],
                })

    # Check 12: Stale task assignment (in-progress with assignee, no updates in 14+ days)
    for task in store.list_tasks(status="in-progress"):
        if task.assignee and task.updated < stale_threshold:
            days = (date.today() - task.updated).days
            findings.append({
                "severity": "warning",
                "check": "stale-assignment",
                "message": f"Task {task.id} assigned to {task.assignee} with no updates for {days} days",
                "items": [task.id],
            })

    # Check 13: Malformed files in quarantine
    malformed_dir = store.project_dir / "malformed"
    if malformed_dir.exists():
        malformed_count = len(list(malformed_dir.glob("*.md")))
        if malformed_count > 0:
            findings.append({
                "severity": "warning",
                "check": "malformed-files",
                "message": f"{malformed_count} file(s) quarantined in .project/malformed/ — run /pm-fix",
                "items": [f.name for f in sorted(malformed_dir.glob("*.md"))[:5]],
            })

    # Generate report
    report_lines = ["# Project Audit Report\n"]

    error_count = sum(1 for f in findings if f["severity"] == "error")
    warn_count = sum(1 for f in findings if f["severity"] == "warning")
    info_count = sum(1 for f in findings if f["severity"] == "info")

    report_lines.append(f"**Errors:** {error_count} | **Warnings:** {warn_count} | **Info:** {info_count}\n")

    if not findings:
        report_lines.append("No issues found. Project is clean.\n")
    else:
        for f in findings:
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}[f["severity"]]
            report_lines.append(f"- {icon} {f['message']}")

    report = "\n".join(report_lines)

    # Write DRIFT.md
    drift_path = store.project_dir / "DRIFT.md"
    drift_path.write_text(report + "\n")

    return report
