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
