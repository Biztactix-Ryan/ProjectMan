"""Pydantic models for ProjectMan data structures."""

import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, field_validator

FIBONACCI_POINTS = {1, 2, 3, 5, 8, 13}


class StoryStatus(str, Enum):
    backlog = "backlog"
    ready = "ready"
    active = "active"
    done = "done"
    archived = "archived"


class EpicStatus(str, Enum):
    draft = "draft"
    active = "active"
    done = "done"
    archived = "archived"


class TaskStatus(str, Enum):
    todo = "todo"
    in_progress = "in-progress"
    review = "review"
    done = "done"
    blocked = "blocked"


def is_archived(meta: Any) -> bool:
    """True if an epic, story, or task is archived.

    Epics and stories carry ``archived`` as a status value; tasks carry it as a
    boolean beside status so the status they had when work stopped survives.
    This helper is the single place callers should ask the question, so
    completion/burndown/velocity math does not have to know which encoding an
    item type uses.
    """
    archived_flag = getattr(meta, "archived", False)
    if archived_flag:
        return True
    status = getattr(meta, "status", None)
    status_value = getattr(status, "value", status)
    return status_value == "archived"


class Priority(str, Enum):
    must = "must"
    should = "should"
    could = "could"
    wont = "wont"


class StoryFrontmatter(BaseModel):
    id: str
    title: str
    status: StoryStatus = StoryStatus.backlog
    priority: Priority = Priority.should
    points: Optional[int] = None
    epic_id: Optional[str] = None
    tags: list[str] = []
    acceptance_criteria: list[str] = []
    depends_on: list[str] = []
    created: date
    updated: date

    @field_validator("points")
    @classmethod
    def validate_fibonacci(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in FIBONACCI_POINTS:
            raise ValueError(
                f"Points must be fibonacci: {sorted(FIBONACCI_POINTS)}"
            )
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(f"Story ID must be alphanumeric with hyphens, got: {v}")
        return v

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, v: list[str]) -> list[str]:
        for dep in v:
            if not re.match(r"^[A-Za-z][\w-]*$", dep):
                raise ValueError(
                    f"depends_on entries must be valid IDs, got: {dep}"
                )
        return v


class EpicFrontmatter(BaseModel):
    id: str
    title: str
    status: EpicStatus = EpicStatus.draft
    priority: Priority = Priority.should
    points: Optional[int] = None
    target_date: Optional[date] = None
    tags: list[str] = []
    created: date
    updated: date

    @field_validator("points")
    @classmethod
    def validate_fibonacci(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in FIBONACCI_POINTS:
            raise ValueError(
                f"Points must be fibonacci: {sorted(FIBONACCI_POINTS)}"
            )
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(
                f"Epic ID must be alphanumeric with hyphens, got: {v}"
            )
        return v


class TaskFrontmatter(BaseModel):
    id: str
    story_id: str
    title: str
    status: TaskStatus = TaskStatus.todo
    # Archival is orthogonal to status: a task can be archived from any status
    # and keeps the status it had when work stopped.  Defaults to False so task
    # files written before this field existed still parse.
    archived: bool = False
    points: Optional[int] = None
    assignee: Optional[str] = None
    tags: list[str] = []
    depends_on: list[str] = []
    created: date
    updated: date

    @field_validator("points")
    @classmethod
    def validate_fibonacci(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in FIBONACCI_POINTS:
            raise ValueError(
                f"Points must be fibonacci: {sorted(FIBONACCI_POINTS)}"
            )
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(
                f"Task ID must be alphanumeric with hyphens, got: {v}"
            )
        return v

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, v: list[str]) -> list[str]:
        for dep in v:
            if not re.match(r"^[A-Za-z][\w-]*$", dep):
                raise ValueError(
                    f"depends_on entries must be valid task IDs, got: {dep}"
                )
        return v


class SprintStatus(str, Enum):
    planning = "planning"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class SprintFrontmatter(BaseModel):
    id: str
    name: str
    status: SprintStatus = SprintStatus.planning
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    planned_stories: list[str] = []
    planned_points: int = 0
    completed_points: int = 0
    goal: str = ""
    created: date
    updated: date

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(
                f"Sprint ID must be alphanumeric with hyphens, got: {v}"
            )
        return v


class ChangesetStatus(str, Enum):
    open = "open"
    partial = "partial"
    merged = "merged"
    closed = "closed"


class ChangesetEntry(BaseModel):
    """A single project's participation in a changeset."""

    project: str
    ref: str = ""
    pr_number: Optional[int] = None
    status: str = "pending"


class ChangesetFrontmatter(BaseModel):
    id: str
    title: str
    status: ChangesetStatus = ChangesetStatus.open
    entries: list[ChangesetEntry] = []
    created: date
    updated: date

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(
                f"Changeset ID must be alphanumeric with hyphens, got: {v}"
            )
        return v


class ProjectConfig(BaseModel):
    name: str
    prefix: str = "PRJ"
    description: str = ""
    repo: str = ""
    hub: bool = False
    auto_commit: bool = False
    deploy_branch: Optional[str] = None
    next_story_id: int = 1
    next_epic_id: int = 1
    next_changeset_id: int = 1
    next_sprint_id: int = 1
    projects: list[str] = []

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        if not v.isalpha() or not v.isupper():
            raise ValueError("Prefix must be uppercase letters")
        return v


class IndexEntry(BaseModel):
    id: str
    title: str
    type: str  # "story", "task", or "epic"
    status: str
    # Tasks carry archival as a flag beside status; epics/stories encode it in
    # status itself, so this stays False for them.
    archived: bool = False
    points: Optional[int] = None
    story_id: Optional[str] = None
    epic_id: Optional[str] = None
    tags: list[str] = []


class ProjectIndex(BaseModel):
    entries: list[IndexEntry] = []
    total_points: int = 0
    completed_points: int = 0
    story_count: int = 0
    task_count: int = 0
    epic_count: int = 0


class Outcome(str, Enum):
    success = "success"
    partial = "partial"
    blocked = "blocked"
    failed = "failed"
    info = "info"


#: Caps on the bounded ``Evidence`` payload — see
#: ``docs/reference/evidence-contract.md`` §1.  They are *clamped, never
#: rejected*: an oversized payload keeps its first N entries rather than
#: taking the status/outcome write down with it.  Worst case on the wire is
#: ~16 KiB; the expected case is 300-600 bytes.
EVIDENCE_MAX_FILES = 40
EVIDENCE_MAX_TESTS = 10
EVIDENCE_MAX_DOD = 20
EVIDENCE_MAX_STRING = 160


class EvidenceTest(BaseModel):
    """One test command that was run, and whether it passed."""

    command: str
    passed: bool
    summary: Optional[str] = None


# The note says what happened; the evidence says what proves it.  Nothing
# open-ended is added here on purpose — an ``extra`` dict is how this becomes
# the next unbounded blob the note already was.  ``dod_unmet`` earns its
# place: ``pm_review`` and ``pm_park`` exist to say *which* criteria are
# outstanding, and without it that list goes straight back into the prose.
#
# The class docstring is the ``description`` in every tool schema that takes
# an Evidence parameter, so it stays one line: six tools pay for it.
class Evidence(BaseModel):
    """Structured proof for a run-log entry: files changed, tests run, DoD criteria met/unmet. Over-long lists and strings are clamped, never rejected."""

    files: list[str] = []
    tests: list[EvidenceTest] = []
    dod_met: list[str] = []
    dod_unmet: list[str] = []

    def summary(self) -> str:
        """One compact line, e.g. ``"3 files, 1/1 tests passed, 2/2 DoD"``.

        What ``pm_get(include_log=True)`` shows instead of the object: it is
        the high-frequency context call, and embedding the full evidence
        there spends the exact budget this contract defends.
        """
        passed = sum(1 for t in self.tests if t.passed)
        dod_total = len(self.dod_met) + len(self.dod_unmet)
        return (
            f"{len(self.files)} files, "
            f"{passed}/{len(self.tests)} tests passed, "
            f"{len(self.dod_met)}/{dod_total} DoD"
        )


class RunLogEntry(BaseModel):
    """A single run-log entry recording an attempt or note on an item."""

    timestamp: datetime
    outcome: Outcome
    status: Optional[str] = None
    note: str
    actor: str
    #: Optional structured evidence.  A field with a default is simply absent
    #: from every pre-existing ``.jsonl`` line, so old logs parse to
    #: ``evidence=None`` with no migration and no version marker.
    evidence: Optional[Evidence] = None


class EventType(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"
    archive = "archive"


class ItemType(str, Enum):
    story = "story"
    task = "task"
    epic = "epic"
    changeset = "changeset"
    sprint = "sprint"


class LogSource(str, Enum):
    mcp = "mcp"
    web = "web"
    cli = "cli"


class LogEntry(BaseModel):
    """Activity log entry capturing a single project mutation."""

    event_type: EventType
    item_id: str
    item_type: ItemType
    changes: dict[str, Any] = {}
    timestamp: datetime
    actor: str
    source: LogSource
