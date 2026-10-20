"""Decision blocking: which open decisions stand in a task's way (US-PM-64).

A decision blocks every id in its ``blocks`` list.  A task listed there is
blocked directly; a story listed there blocks all of its tasks; an epic
listed there blocks every task under its stories.  Only ``open`` decisions
block -- answered and withdrawn ones never do.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from .models import (
    EPIC_ID,
    TASK_ID,
    DecisionFrontmatter,
    DecisionStatus,
    StoryFrontmatter,
    TaskFrontmatter,
    TaskStatus,
)

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


# ─── Blocked points (US-PM-63-9, US-PM-67-5) ─────────────────────


def blocked_task_reach(
    store: "Store",
) -> tuple[Callable[[Iterable[str]], set[str]], dict[str, TaskFrontmatter]]:
    """``(reach, open_tasks)``: the open task IDs a ``blocks`` list holds up.

    Open means neither ``done`` nor archived.  ``reach(blocks)`` is the set of
    open task IDs named directly, every open task of a named story, and every
    open task under every story of a named epic -- a set, so a task reached
    twice is one task.  One listing of tasks and stories serves every call.
    """
    open_tasks = {
        t.id: t
        for t in store.list_tasks(archived=False)
        if t.status != TaskStatus.done
    }
    tasks_by_story: dict[str, list[str]] = {}
    for task in open_tasks.values():
        tasks_by_story.setdefault(task.story_id, []).append(task.id)
    stories_by_epic: dict[str, list[str]] = {}
    for story in store.list_stories():
        if story.epic_id:
            stories_by_epic.setdefault(story.epic_id, []).append(story.id)

    def reach(blocks: Iterable[str]) -> set[str]:
        task_ids: set[str] = set()
        for item_id in blocks:
            if EPIC_ID.match(item_id):
                for story_id in stories_by_epic.get(item_id, []):
                    task_ids.update(tasks_by_story.get(story_id, []))
            elif TASK_ID.match(item_id):
                if item_id in open_tasks:
                    task_ids.add(item_id)
            else:
                task_ids.update(tasks_by_story.get(item_id, []))
        return task_ids

    return reach, open_tasks


def blocked_points_counter(store: "Store") -> Callable[[Iterable[str]], int]:
    """A function mapping a decision's ``blocks`` list to its blocked points.

    The points of the open tasks :func:`blocked_task_reach` finds; a task with
    no estimate counts zero.
    """
    reach, open_tasks = blocked_task_reach(store)

    def blocked_points(blocks: Iterable[str]) -> int:
        return sum(open_tasks[t].points or 0 for t in reach(blocks))

    return blocked_points


def open_decision_summary(store: "Store") -> dict[str, int]:
    """``{open, blocked_points}`` over every open decision in *store*.

    ``blocked_points`` is the points of the *union* of the open tasks the open
    decisions hold up, so a task blocked by several decisions counts once --
    the number answers "how much work is waiting on answers", not the sum of
    the per-decision ``pm_list_decisions`` figures.  Answered and withdrawn
    decisions are excluded.  Zeros when there are none.
    """
    decisions = store.list_decisions(status=DecisionStatus.open.value)
    if not decisions:
        return {"open": 0, "blocked_points": 0}
    reach, open_tasks = blocked_task_reach(store)
    held: set[str] = set()
    for decision in decisions:
        held |= reach(decision.blocks)
    return {
        "open": len(decisions),
        "blocked_points": sum(open_tasks[t].points or 0 for t in held),
    }


# ─── Promoting an answer to an ADR (US-PM-66-6) ─────────────────

_ADR_HEADING = re.compile(r"^## ADR-(\d+)\b", re.MULTILINE)
_ADR_START = re.compile(r'^(?:<a id="adr-\d+"></a>|## ADR-\d+\b)', re.MULTILINE)

#: The header a DECISIONS.md created by a promotion starts with.
DECISIONS_HEADER = (
    "# Decisions\n\n"
    "Architectural decision record. Newest first. Each entry: context, "
    "decision, alternatives rejected.\n\n---\n"
)


def next_adr_number(text: str) -> int:
    """One past the highest ``## ADR-NNN`` heading in *text*; 1 when none.

    The highest, not the count: a gap left by a removed ADR is never reused.
    """
    numbers = [int(n) for n in _ADR_HEADING.findall(text)]
    return max(numbers, default=0) + 1


def render_adr(number: int, decision: DecisionFrontmatter, body: str) -> str:
    """The ADR entry for an answered *decision*, in DECISIONS.md's format.

    Context is the decision's body, Decision its answer (with the chosen
    option's summary) and rationale, Alternatives rejected every other
    option; the Status line cites the DEC id.
    """
    adr_id = f"ADR-{number:03d}"
    when = (decision.answered_at.date() if decision.answered_at else decision.updated)
    chosen = next((o for o in decision.options if o.label == decision.answer), None)
    decided = decision.answer or ""
    if chosen is not None and chosen.summary:
        decided += f" — {chosen.summary}"
    decided = _sentence(decided)
    if decision.rationale:
        decided += f" Rationale: {_sentence(decision.rationale)}"
    rejected = [o for o in decision.options if o is not chosen]
    lines = [
        f"- **{o.label}.**"
        + (f" {_sentence(o.summary)}" if o.summary else "")
        + (f" Cons: {_sentence('; '.join(o.cons))}" if o.cons else "")
        for o in rejected
    ] or ["- None recorded."]
    by = f", answered by {decision.answered_by}" if decision.answered_by else ""
    return (
        f'<a id="adr-{number:03d}"></a>\n\n'
        f"## {adr_id}: {decision.title} ({when.isoformat()})\n\n"
        f"**Status:** Accepted ({when.isoformat()}) — promoted from "
        f"{decision.id}{by}.\n\n"
        f"**Context.** {body.strip() or '(none recorded)'}\n\n"
        f"**Decision.** {decided}\n\n"
        "**Alternatives rejected.**\n\n" + "\n".join(lines) + "\n"
    )


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


def insert_adr(text: Optional[str], entry: str) -> str:
    """*text* with *entry* added newest-first, as DECISIONS.md is kept.

    It goes above the first existing ADR, separated by ``---``; with no ADR
    yet it is appended at the end; with no file it follows a fresh header.
    """
    if text is None or not text.strip():
        return f"{DECISIONS_HEADER}\n{entry}"
    first = _ADR_START.search(text)
    if first is None:
        return f"{text.rstrip()}\n\n{entry}"
    return f"{text[:first.start()]}{entry}\n---\n\n{text[first.start():]}"
