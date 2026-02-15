"""Scoping support — provides context for LLM-driven story decomposition."""

from pathlib import Path
from typing import Optional

import yaml

from .store import Store


def scope(store: Store, story_id: str) -> str:
    """Return story content + existing tasks + decomposition guidance."""
    meta, body = store.get_story(story_id)
    existing_tasks = store.list_tasks(story_id=story_id)

    guidance = {
        "rules": [
            "Each task should be completable in one session (1-5 points)",
            "Tasks should be independently testable",
            "Include implementation + testing in each task",
            "First task should set up the foundation",
            "Last task should handle integration/cleanup",
        ],
        "task_template": {
            "title": "Verb phrase describing the deliverable",
            "description": "Include: what to implement, acceptance criteria, files to touch",
            "points": "Fibonacci: 1, 2, 3, 5 (avoid 8+ for single tasks)",
        },
    }

    result = {
        "story": meta.model_dump(mode="json"),
        "story_body": body,
        "existing_tasks": [t.model_dump(mode="json") for t in existing_tasks],
        "task_count": len(existing_tasks),
        "decomposition_guidance": guidance,
    }

    return yaml.dump(result, default_flow_style=False, sort_keys=False)


def auto_scope(store: Store, mode: Optional[str] = None) -> str:
    """Discover what needs scoping — full codebase scan or incremental story decomposition.

    Auto-detects mode based on project state:
    - Full scan: no epics AND no stories exist (or mode="full")
    - Incremental: stories exist that have no tasks (or mode="incremental")
    """
    epics = store.list_epics()
    stories = store.list_stories()

    # Auto-detect mode
    if mode is None:
        if not epics and not stories:
            mode = "full"
        else:
            mode = "incremental"

    if mode == "full":
        return _auto_scope_full(store)
    else:
        return _auto_scope_incremental(store)


def _auto_scope_full(store: Store) -> str:
    """Full scan — read project docs, build files, source tree for new project discovery."""
    root = store.root
    signals = {}

    # Read project documentation files
    doc_files = ["README.md", "PROJECT.md", "INFRASTRUCTURE.md", "SECURITY.md"]
    docs = {}
    for name in doc_files:
        # Check both root and .project/ for docs
        for candidate in [root / name, root / ".project" / name]:
            if candidate.exists():
                docs[name] = candidate.read_text()
                break
    if docs:
        signals["documentation"] = docs

    # Detect and read build files (first 200 lines each)
    build_files = [
        "pyproject.toml", "setup.py", "setup.cfg",
        "package.json", "package-lock.json",
        "Cargo.toml", "go.mod", "go.sum",
        "Makefile", "CMakeLists.txt",
        "Gemfile", "pom.xml", "build.gradle",
        "requirements.txt", "Pipfile",
    ]
    builds = {}
    for name in build_files:
        path = root / name
        if path.exists():
            lines = path.read_text().splitlines()[:200]
            builds[name] = "\n".join(lines)
    if builds:
        signals["build_files"] = builds

    # Generate source tree (2 levels deep, excluding noise)
    exclude_dirs = {
        ".venv", ".git", "node_modules", "__pycache__", ".tox",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist",
        "build", ".egg-info", ".eggs", "target", "vendor",
    }
    tree_lines = _tree(root, depth=2, exclude=exclude_dirs)
    signals["source_tree"] = "\n".join(tree_lines)

    # Guidance for epic/story creation
    signals["guidance"] = {
        "epic_template": {
            "title": "Short strategic name for a major initiative",
            "description": "Vision, success criteria, and scope",
            "priority": "must / should / could / wont",
        },
        "story_template": {
            "title": "As a [user], I want [goal] so that [benefit]",
            "description": "Acceptance criteria, notes, context",
            "priority": "must / should / could / wont",
            "points": "Fibonacci: 1, 2, 3, 5, 8, 13",
        },
        "task_template": {
            "title": "Verb phrase describing the deliverable",
            "description": "What to implement, acceptance criteria, files to touch",
            "points": "Fibonacci: 1, 2, 3, 5 (avoid 8+ for single tasks)",
        },
        "rules": [
            "Group related stories under epics",
            "Each story should represent user-visible value",
            "Each task should be completable in one session (1-5 points)",
            "Tasks should be independently testable",
            "Include implementation + testing in each task",
        ],
    }

    signals["mode"] = "full"
    signals["project"] = store.config.name
    signals["prefix"] = store.config.prefix

    return yaml.dump(signals, default_flow_style=False, sort_keys=False)


def _auto_scope_incremental(store: Store) -> str:
    """Incremental — find stories with no tasks and return them for decomposition."""
    stories = store.list_stories()
    all_tasks = store.list_tasks()

    # Build task count per story
    task_counts: dict[str, int] = {}
    for t in all_tasks:
        task_counts[t.story_id] = task_counts.get(t.story_id, 0) + 1

    # Find undecomposed stories (non-done/archived, 0 tasks)
    skip_statuses = {"done", "archived"}
    undecomposed = []
    for s in stories:
        if s.status.value in skip_statuses:
            continue
        if task_counts.get(s.id, 0) == 0:
            # Include the story body for context
            _, body = store.get_story(s.id)
            undecomposed.append({
                "story": s.model_dump(mode="json"),
                "body": body,
            })

    result = {
        "mode": "incremental",
        "project": store.config.name,
        "prefix": store.config.prefix,
        "total_stories": len(stories),
        "undecomposed_count": len(undecomposed),
        "undecomposed_stories": undecomposed,
        "decomposition_guidance": {
            "rules": [
                "Each task should be completable in one session (1-5 points)",
                "Tasks should be independently testable",
                "Include implementation + testing in each task",
                "First task should set up the foundation",
                "Last task should handle integration/cleanup",
            ],
            "task_template": {
                "title": "Verb phrase describing the deliverable",
                "description": "Include: what to implement, acceptance criteria, files to touch",
                "points": "Fibonacci: 1, 2, 3, 5 (avoid 8+ for single tasks)",
            },
        },
    }

    return yaml.dump(result, default_flow_style=False, sort_keys=False)


def _tree(root: Path, depth: int, exclude: set[str], prefix: str = "") -> list[str]:
    """Generate a simple directory tree listing."""
    if depth < 0:
        return []

    lines = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return []

    dirs = [e for e in entries if e.is_dir() and e.name not in exclude and not e.name.endswith(".egg-info")]
    files = [e for e in entries if e.is_file()]

    for f in files:
        lines.append(f"{prefix}{f.name}")

    for d in dirs:
        lines.append(f"{prefix}{d.name}/")
        if depth > 0:
            lines.extend(_tree(d, depth - 1, exclude, prefix=prefix + "  "))

    return lines


def scope_epic(store: Store, epic_id: str) -> str:
    """Return epic content + linked stories + decomposition guidance."""
    meta, body = store.get_epic(epic_id)
    linked_stories = [s for s in store.list_stories() if s.epic_id == epic_id]

    guidance = {
        "rules": [
            "Each story should represent a user-visible outcome",
            "Stories should be independent and deliverable on their own",
            "Group related tasks under the same story",
            "A story should be completable in 1-2 sprints (5-13 points)",
            "Cover the epic's success criteria across the stories",
        ],
        "story_template": {
            "title": "As a [user], I want [goal] so that [benefit]",
            "description": "Include: user story, acceptance criteria, notes",
            "priority": "must / should / could / wont",
            "points": "Fibonacci: 1, 2, 3, 5, 8, 13",
        },
    }

    result = {
        "epic": meta.model_dump(mode="json"),
        "epic_body": body,
        "linked_stories": [s.model_dump(mode="json") for s in linked_stories],
        "story_count": len(linked_stories),
        "decomposition_guidance": guidance,
    }

    return yaml.dump(result, default_flow_style=False, sort_keys=False)
