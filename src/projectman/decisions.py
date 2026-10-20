"""Decision blocking: which open decisions stand in a task's way (US-PM-64).

A decision blocks every id in its ``blocks`` list.  A task listed there is
blocked directly; a story listed there blocks all of its tasks; an epic
listed there blocks every task under its stories.  Only ``open`` decisions
block -- answered and withdrawn ones never do.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable, Optional

from .models import DecisionFrontmatter, DecisionStatus, StoryFrontmatter, TaskFrontmatter

if TYPE_CHECKING:  # pragma: no cover
    from .store import Store

_DECISION_NUMBER = re.compile(r"-(\d+)$")


def _decision_sort_key(decision: DecisionFrontmatter) -> tuple[int, str]:
    match = _DECISION_NUMBER.search(decision.id)
    return (int(match.group(1)) if match else -1, decision.id)


def blocking_decisions(
    task_meta: TaskFrontmatter,
    store: Optional["Store"] = None,
    *,
    decisions: Optional[Iterable[DecisionFrontmatter]] = None,
    stories: Optional[dict[str, StoryFrontmatter]] = None,
) -> list[DecisionFrontmatter]:
    """Return the open decisions blocking *task_meta*, ordered by number.

    A decision blocks the task when its ``blocks`` list names the task, the
    task's story, or that story's epic.

    decisions / stories: pre-loaded context for callers that check many
    tasks at once (the board), mirroring ``check_readiness``.  ``decisions``
    may hold every decision or only the open ones -- non-open entries are
    filtered out here either way.  Without it the store is read once via
    ``list_decisions(status="open")``.  ``stories`` is a cache, not an
    authority: a story id missing from it falls back to ``store.get_story``
    (archived stories are absent from ``list_stories`` but still have an
    epic).  With no store and a cache miss, the epic is simply unknown and
    only the task and story ids are matched.
    """
    if decisions is None:
        if store is None:
            raise ValueError("blocking_decisions needs a store or pre-loaded decisions")
        decisions = store.list_decisions(status=DecisionStatus.open.value)

    return _decisions_naming(
        task_meta, store, decisions, DecisionStatus.open, stories=stories
    )


def answered_decisions(
    task_meta: TaskFrontmatter,
    store: Optional["Store"],
    decisions: Iterable[DecisionFrontmatter],
    *,
    stories: Optional[dict[str, StoryFrontmatter]] = None,
) -> list[DecisionFrontmatter]:
    """The answered decisions that blocked *task_meta*, ordered by number.

    The same task / story / epic match as :func:`blocking_decisions`, over
    the pre-loaded ``decisions`` (US-PM-66-5: pm_grab hands these to the
    worker so a settled question is not re-asked).  Withdrawn ones are
    excluded -- they settled nothing.
    """
    return _decisions_naming(
        task_meta, store, decisions, DecisionStatus.answered, stories=stories
    )


def _decisions_naming(
    task_meta: TaskFrontmatter,
    store: Optional["Store"],
    decisions: Iterable[DecisionFrontmatter],
    status: DecisionStatus,
    *,
    stories: Optional[dict[str, StoryFrontmatter]] = None,
) -> list[DecisionFrontmatter]:
    """Decisions in *status* whose ``blocks`` name the task, story or epic."""
    candidates = [d for d in decisions if d.status == status]
    if not candidates:
        return []

    targets = {task_meta.id}
    if task_meta.story_id:
        targets.add(task_meta.story_id)
        story_meta = stories.get(task_meta.story_id) if stories is not None else None
        if story_meta is None and store is not None:
            try:
                story_meta, _ = store.get_story(task_meta.story_id)
            except FileNotFoundError:
                story_meta = None
        if story_meta is not None and story_meta.epic_id:
            targets.add(story_meta.epic_id)

    matched = [d for d in candidates if targets.intersection(d.blocks)]
    matched.sort(key=_decision_sort_key)
    return matched
