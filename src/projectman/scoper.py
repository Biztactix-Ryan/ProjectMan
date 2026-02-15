"""Scoping support — provides context for LLM-driven story decomposition."""

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
