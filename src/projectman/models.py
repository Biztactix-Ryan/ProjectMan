"""Pydantic models for ProjectMan data structures."""

import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

FIBONACCI_POINTS = {1, 2, 3, 5, 8, 13}

#: Default claim-staleness threshold, in hours (US-PM-14-5).  Named once so
#: the field default and the fallback a malformed config value lands on cannot
#: drift apart.
DEFAULT_STALE_CLAIM_HOURS = 2.0


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
    # --- Claim ownership (US-PM-14-5) --------------------------------
    # `assignee` says *who* holds the task; these two say *which run* took
    # it and *when*.  That is the difference between "claimed by claude" --
    # true of every task any agent ever touched -- and "claimed by the run
    # that died forty minutes ago", which is the question a restarting
    # orchestrator actually has to answer.
    #
    # Both default to None so every task file written before this field
    # existed still parses, and a claim with no `claimed_at` is treated as
    # *unknown age*, never as stale: inferring staleness from a missing
    # timestamp would silently steal live work from an older writer.
    #
    # Cleared on release and on done -- see store.CLEARABLE_FIELDS.  They
    # describe a claim in force, not a historical fact; `assignee` is what
    # records who did the work on a finished task.
    claimed_at: Optional[datetime] = None
    claimed_by_run: Optional[str] = None
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

    @field_validator("claimed_at")
    @classmethod
    def normalize_claimed_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Normalise to a UTC-aware datetime.

        The value round-trips through YAML frontmatter, which hands back
        either a string or a naive ``datetime`` depending on how the file was
        written.  A naive value is read as UTC rather than as local time:
        claims are written from ``datetime.now(timezone.utc)``, and guessing
        local here would make a claim look hours old -- or hours in the
        future -- purely from the reader's zone.
        """
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

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


class ToolFlags(BaseModel):
    """Opt-in switches for the tool families hidden from the agent tool list.

    Every field defaults to "off" for a plain single-project repo: the
    families behind these flags were called zero times across ~14,200
    recorded tool calls, so their schemas were pure token cost in every
    request (US-PM-15).  The functions are untouched and stay importable —
    only their MCP registration is conditional.

    ``changesets`` is deliberately tri-state.  ``None`` (the default, and
    what an untouched ``config.yaml`` yields) means *follow hub mode*: a
    changeset groups a change across several projects, which only a hub
    has, so a hub gets the family and a single-project repo does not.  An
    explicit ``true``/``false`` always wins over that inference.

    ``maintenance`` is the break-glass cluster — ``pm_repair``,
    ``pm_restore``, ``pm_validate_branches``, ``pm_fix_malformed`` and
    ``pm_push_all``.  These are human recovery tools, not agent work, and
    every one has a ``projectman`` CLI equivalent, so hiding them from the
    tool list costs nobody reach.  Plain ``bool``: no hub inference,
    because a hub needs repairing no more routinely than a leaf repo does.
    """

    changesets: Optional[bool] = None
    maintenance: bool = False
    web: bool = False


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
    tools: ToolFlags = Field(default_factory=ToolFlags)
    #: How long a claim may sit untouched before `pm_active` / `pm_board`
    #: flag it `stale: true` (US-PM-14-5).  Two hours is roughly four times
    #: the longest single task in the corpus, so a task still being worked
    #: is not accused, while a run that died is visible well inside the next
    #: orchestrator loop.  A float so a fast pool can say `0.25`; set it
    #: high rather than to 0 to disable -- 0 would flag every live claim.
    stale_claim_hours: float = DEFAULT_STALE_CLAIM_HOURS

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        if not v.isalpha() or not v.isupper():
            raise ValueError("Prefix must be uppercase letters")
        return v

    @field_validator("stale_claim_hours", mode="before")
    @classmethod
    def tolerate_a_junk_threshold(cls, v: object) -> float:
        """A malformed `stale_claim_hours` falls back to the default (US-PM-14-2).

        Every other field here describes the project; this one only tunes an
        *annotation* on two read tools.  Raising on it would take the whole
        config load down -- and with it every tool in the server, since
        `load_config` builds this model once for the store -- so a typo in an
        optional tuning knob would look like a broken project.  Falling back
        keeps staleness answerable at the documented default instead.

        Rejected and replaced: anything `float()` refuses, NaN/infinity (no
        claim could ever cross an infinite threshold, and NaN compares false
        against everything, so both silently disable staleness), and a
        negative value (which would flag every live claim).  Zero is *kept* --
        it is a meaningful, if aggressive, setting, and the field's own doc
        comment tells a reader what it does.
        """
        if v is None:
            return DEFAULT_STALE_CLAIM_HOURS
        try:
            parsed = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return DEFAULT_STALE_CLAIM_HOURS
        if not math.isfinite(parsed) or parsed < 0:
            return DEFAULT_STALE_CLAIM_HOURS
        return parsed


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
    #: Which orchestrator run made this mutation, when the mutation is one
    #: that has an owner -- claim, release, verdict (US-PM-14-5).  ``actor``
    #: is too coarse for recovery: every run of every agent on a machine
    #: shares one actor, so "what did *my* previous run claim" cannot be
    #: answered from it.  Left None on the ordinary edits that belong to no
    #: run in particular, which is also what every pre-existing log line
    #: parses to -- an absent field with a default needs no migration.
    run_id: Optional[str] = None
