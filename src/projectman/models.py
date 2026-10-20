"""Pydantic models for ProjectMan data structures."""

import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

FIBONACCI_POINTS = {1, 2, 3, 5, 8, 13}

#: Charset for the project prefix embedded in every ID (US-PRJ-50-6).
#:
#: Uppercase alphanumeric, because that is what actually produces prefixes:
#: ``cli.py`` defaults to ``PRJ``.  Kept as a raw *fragment* rather than a compiled
#: pattern because its only job is to be interpolated into the four anchored
#: patterns below — it is not anchored and must never be matched on its own.
PREFIX = r"[A-Z][A-Z0-9]*"

#: Anchored, compiled ID patterns.  These replace the permissive
#: ``^[A-Za-z][\w-]*$`` that previously accepted anything vaguely
#: identifier-shaped, so a malformed ID is caught at creation time instead of
#: surfacing later as a dangling reference.  Exported so callers outside this
#: module (store lookups, ID resolution) can reuse one definition rather than
#: re-deriving the shapes.
STORY_ID = re.compile(rf"^US-{PREFIX}-\d+$")
TASK_ID = re.compile(rf"^US-{PREFIX}-\d+-\d+$")
EPIC_ID = re.compile(rf"^EPIC-{PREFIX}-\d+$")
SPRINT_ID = re.compile(rf"^SPRINT-{PREFIX}-\d+$")
DECISION_ID = re.compile(rf"^DEC-{PREFIX}-\d+$")
#: An architectural decision record heading in DECISIONS.md (US-PM-66-6).
ADR_ID = re.compile(r"^ADR-\d{3,}$")

#: Default claim-staleness threshold, in hours (US-PM-14-5).  Named once so
#: the field default and the fallback a malformed config value lands on cannot
#: drift apart.
DEFAULT_STALE_CLAIM_HOURS = 2.0

#: Default ceiling on how long one task should take, in minutes (US-PM-50-7).
#: Sixty is the orchestrator's prompt-cache TTL: a worker that runs past it
#: costs the run a full prefix rewrite on the next dispatch, so a points band
#: whose p90 sits above this is worth splitting before the sprint starts.
#: Named once so the field default and the malformed-value fallback cannot
#: drift apart.
DEFAULT_MAX_TASK_MINUTES = 60.0

#: Default age, in days, past which an open decision is reported stale by
#: ``pm_audit`` (US-PM-67-7).  Two weeks is one sprint's length here: a
#: question still open after a whole sprint is either holding work up or no
#: longer being asked.  Named once so the field default and the
#: malformed-value fallback cannot drift apart.
DEFAULT_DECISION_STALE_DAYS = 14.0


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
        if not STORY_ID.match(v):
            raise ValueError(
                f"Story ID must match {STORY_ID.pattern} "
                f"(e.g. US-PRJ-1), got: {v}"
            )
        return v

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, v: list[str]) -> list[str]:
        # A story may depend on another story or on a single task — see the
        # pm_create_story docstring — so both shapes are accepted here.
        for dep in v:
            if not (STORY_ID.match(dep) or TASK_ID.match(dep)):
                raise ValueError(
                    f"Story depends_on entries must be a story ID matching "
                    f"{STORY_ID.pattern} (e.g. US-PRJ-1) or a task ID matching "
                    f"{TASK_ID.pattern} (e.g. US-PRJ-1-1), got: {dep}"
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
        if not EPIC_ID.match(v):
            raise ValueError(
                f"Epic ID must match {EPIC_ID.pattern} "
                f"(e.g. EPIC-PRJ-1), got: {v}"
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
        if not TASK_ID.match(v):
            raise ValueError(
                f"Task ID must match {TASK_ID.pattern} "
                f"(e.g. US-PRJ-1-1), got: {v}"
            )
        return v

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, v: list[str]) -> list[str]:
        # Tasks block on other tasks only: a story is not a unit of work that
        # can be observed to finish, so a story ID here would never clear.
        for dep in v:
            if not TASK_ID.match(dep):
                raise ValueError(
                    f"Task depends_on entries must be task IDs matching "
                    f"{TASK_ID.pattern} (e.g. US-PRJ-1-1), got: {dep}"
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
        if not SPRINT_ID.match(v):
            raise ValueError(
                f"Sprint ID must match {SPRINT_ID.pattern} "
                f"(e.g. SPRINT-PRJ-1), got: {v}"
            )
        return v


class DecisionStatus(str, Enum):
    open = "open"
    answered = "answered"
    withdrawn = "withdrawn"


def _is_blockable_id(value: str) -> bool:
    """True if *value* has the shape of an item a decision can block.

    Shape only: whether the item exists is a store lookup, not a model
    concern, so it is checked where decisions are written (US-PM-63).
    """
    return bool(TASK_ID.match(value) or STORY_ID.match(value) or EPIC_ID.match(value))


class DecisionOption(BaseModel):
    """One candidate answer to a decision's question."""

    label: str
    summary: str = ""
    pros: list[str] = []
    cons: list[str] = []

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        # The label is what `recommendation` and `answer` refer to, so a
        # blank one could never be picked.
        v = v.strip()
        if not v:
            raise ValueError("Decision option label must not be empty")
        return v


class DecisionFrontmatter(BaseModel):
    id: str
    #: The question, short.  The context lives in the markdown body.
    title: str
    status: DecisionStatus = DecisionStatus.open
    priority: Priority = Priority.should
    #: Items that cannot proceed until this is answered: task, story or epic
    #: IDs.  Validated as shapes here; existence is the store's job.
    blocks: list[str] = []
    #: Who asked -- an agent or a human.
    raised_by: Optional[str] = None
    #: The item the question came up while working on, if any.
    raised_from: Optional[str] = None
    options: list[DecisionOption] = []
    #: Label of the recommended option, if there is one.
    recommendation: Optional[str] = None
    #: The answer: an option label or free text.
    answer: Optional[str] = None
    rationale: Optional[str] = None
    answered_by: Optional[str] = None
    answered_at: Optional[datetime] = None
    #: The ADR this answer was promoted to in DECISIONS.md (US-PM-66-6).
    adr: Optional[str] = None
    created: date
    updated: date

    @field_validator("adr")
    @classmethod
    def validate_adr(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not ADR_ID.match(v):
            raise ValueError(f"Decision adr must look like ADR-001, got: {v}")
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not DECISION_ID.match(v):
            raise ValueError(
                f"Decision ID must match {DECISION_ID.pattern} "
                f"(e.g. DEC-PRJ-1), got: {v}"
            )
        return v

    @field_validator("blocks")
    @classmethod
    def validate_blocks(cls, v: list[str]) -> list[str]:
        for item_id in v:
            if not _is_blockable_id(item_id):
                raise ValueError(
                    f"Decision blocks entries must be a task ID matching "
                    f"{TASK_ID.pattern} (e.g. US-PRJ-1-1), a story ID matching "
                    f"{STORY_ID.pattern} (e.g. US-PRJ-1) or an epic ID matching "
                    f"{EPIC_ID.pattern} (e.g. EPIC-PRJ-1), got: {item_id}"
                )
        return v

    @field_validator("raised_from")
    @classmethod
    def validate_raised_from(cls, v: Optional[str]) -> Optional[str]:
        # A question can come up while working on an item or while answering
        # another decision, so a decision ID is accepted here as well.
        if v is not None and not (_is_blockable_id(v) or DECISION_ID.match(v)):
            raise ValueError(
                f"Decision raised_from must be a task, story, epic or decision "
                f"ID (e.g. US-PRJ-1-1, US-PRJ-1, EPIC-PRJ-1, DEC-PRJ-1), got: {v}"
            )
        return v

    @field_validator("options")
    @classmethod
    def validate_unique_labels(
        cls, v: list[DecisionOption]
    ) -> list[DecisionOption]:
        # Labels are how recommendation and answer name an option; two
        # options sharing one would make that reference ambiguous.
        seen: set[str] = set()
        for option in v:
            if option.label in seen:
                raise ValueError(
                    f"Decision option labels must be unique, got duplicate: "
                    f"{option.label}"
                )
            seen.add(option.label)
        return v

    @field_validator("recommendation")
    @classmethod
    def validate_recommendation(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if v is None:
            return v
        # `options` is declared before `recommendation`, so it has already
        # been validated -- unless it failed, in which case that error is
        # the one worth reporting and this check has nothing to compare to.
        if "options" not in info.data:
            return v
        labels = [option.label for option in info.data["options"]]
        if v not in labels:
            raise ValueError(
                f"Decision recommendation must be one of the option labels "
                f"{labels}, got: {v}"
            )
        return v

    @field_validator("answered_at", mode="before")
    @classmethod
    def coerce_answered_at(cls, v: Any) -> Any:
        # A hand-edited file may carry a bare date, which YAML hands back as
        # a `date`; read it as midnight UTC rather than rejecting the file.
        if isinstance(v, date) and not isinstance(v, datetime):
            return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
        return v

    @field_validator("answered_at")
    @classmethod
    def normalize_answered_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        # Same rule as TaskFrontmatter.claimed_at: naive means UTC.
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class ToolFlags(BaseModel):
    """Opt-in switches for the tool families hidden from the agent tool list.

    Every field defaults to "off" for a plain single-project repo: the
    families behind these flags were called zero times across ~14,200
    recorded tool calls, so their schemas were pure token cost in every
    request (US-PM-15).  The functions are untouched and stay importable —
    only their MCP registration is conditional.

    ``maintenance`` is the break-glass cluster — ``pm_restore`` and
    ``pm_fix_malformed``.  These are human recovery tools, not agent work,
    and both have a ``projectman`` CLI equivalent, so hiding them from the
    tool list costs nobody reach.  Plain ``bool``: no inference from
    anything else, because it is off until someone writes ``true``.
    """

    maintenance: bool = False
    web: bool = False


class OrchestrateConfig(BaseModel):
    """Knobs for orchestrated runs — the `orchestrate:` section of config.yaml.

    A nested section rather than a flat key, for the same reason `tools:`
    is one: these tune the orchestrator loop rather than describe the
    project, and grouping them keeps a dotted name (`orchestrate.max_task_minutes`)
    readable in docs and skills.  Absent from config.yaml, the section
    defaults whole, so no existing project needs an edit.
    """

    #: Longest a single task should be expected to run, in minutes
    #: (US-PM-50).  Planning tools flag a points band whose measured p90
    #: duration sits above this as `long_task_risk`, because a worker that
    #: overruns the one-hour prompt-cache window makes the next dispatch pay
    #: a full prefix rewrite.  A float so a fast pool can say `20.5`; set it
    #: high rather than to 0 to disable -- 0 would flag every band.
    max_task_minutes: float = DEFAULT_MAX_TASK_MINUTES

    @field_validator("max_task_minutes", mode="before")
    @classmethod
    def tolerate_a_junk_ceiling(cls, v: object) -> float:
        """A malformed `max_task_minutes` falls back to the default.

        Same reasoning as `stale_claim_hours`: this key only tunes an
        *annotation* on planning tools, and `load_config` builds this model
        once for the store, so raising on a typo would take every tool in
        the server down.  Rejected and replaced: anything `float()` refuses,
        NaN/infinity (nothing could ever exceed an infinite ceiling, and NaN
        compares false against everything, so both silently disable the
        check), and a negative value (which would flag every band).  Zero is
        *kept* -- aggressive, but a meaningful "flag everything" setting.
        """
        if v is None:
            return DEFAULT_MAX_TASK_MINUTES
        try:
            parsed = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return DEFAULT_MAX_TASK_MINUTES
        if not math.isfinite(parsed) or parsed < 0:
            return DEFAULT_MAX_TASK_MINUTES
        return parsed


class ProjectConfig(BaseModel):
    name: str
    prefix: str = "PRJ"
    description: str = ""
    repo: str = ""
    auto_commit: bool = False
    deploy_branch: Optional[str] = None
    next_story_id: int = 1
    next_epic_id: int = 1
    next_sprint_id: int = 1
    tools: ToolFlags = Field(default_factory=ToolFlags)
    #: Orchestrated-run knobs (US-PM-50).  Nested like `tools:`; defaults
    #: whole when the section is absent from config.yaml.
    orchestrate: OrchestrateConfig = Field(default_factory=OrchestrateConfig)
    #: How long a claim may sit untouched before `pm_active` / `pm_board`
    #: flag it `stale: true` (US-PM-14-5).  Two hours is roughly four times
    #: the longest single task in the corpus, so a task still being worked
    #: is not accused, while a run that died is visible well inside the next
    #: orchestrator loop.  A float so a fast pool can say `0.25`; set it
    #: high rather than to 0 to disable -- 0 would flag every live claim.
    stale_claim_hours: float = DEFAULT_STALE_CLAIM_HOURS
    #: How many days a decision may stay ``open`` before ``pm_audit`` warns
    #: `decision-stale` (US-PM-67-7).  Measured from the decision's
    #: ``created`` date; a decision must *pass* this age, so exactly at the
    #: threshold is not yet stale.  Set it high rather than to 0 to disable --
    #: 0 flags every open decision older than today.
    decision_stale_days: float = DEFAULT_DECISION_STALE_DAYS
    #: Bounds on the activity log (US-PRJ-52-10).  Both default to None,
    #: meaning the log grows forever exactly as it always has; set either
    #: and the append that finds `activity.jsonl` over the bound rotates it
    #: to a dated sibling first.  Size is the file's bytes on disk; age is
    #: measured from the log's *oldest* entry, so a busy log still rotates.
    activity_log_max_bytes: Optional[int] = None
    activity_log_max_days: Optional[float] = None

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

    @field_validator("decision_stale_days", mode="before")
    @classmethod
    def tolerate_a_junk_decision_age(cls, v: object) -> float:
        """A malformed `decision_stale_days` falls back to the default.

        Same reasoning as `stale_claim_hours`: the key only tunes one audit
        warning, and raising on a typo would take `load_config` -- and every
        tool in the server -- down with it.  Anything `float()` refuses,
        NaN/infinity and a negative value are replaced; zero is kept.
        """
        if v is None:
            return DEFAULT_DECISION_STALE_DAYS
        try:
            parsed = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return DEFAULT_DECISION_STALE_DAYS
        if not math.isfinite(parsed) or parsed < 0:
            return DEFAULT_DECISION_STALE_DAYS
        return parsed

    @field_validator("activity_log_max_bytes", "activity_log_max_days", mode="before")
    @classmethod
    def tolerate_a_junk_log_bound(cls, v: object, info: ValidationInfo) -> object:
        """A malformed activity-log bound means "no bound", not a broken project.

        Same reasoning as `stale_claim_hours`: these two keys tune
        housekeeping on a file nothing reads for correctness, and raising
        on a typo would take `load_config` — and with it every tool in the
        server — down. Anything `float()` refuses, a non-finite value, and
        anything at or below zero all fall back to `None` (never rotate).
        Zero is *not* kept here, unlike `stale_claim_hours`: a bound of
        zero would rotate on every append, which nobody means by it. A
        fractional byte count is floored rather than rejected.
        """
        if v is None:
            return None
        try:
            parsed = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed) or parsed <= 0:
            return None
        if info.field_name == "activity_log_max_bytes":
            return int(parsed)
        return parsed


class IndexEntry(BaseModel):
    id: str
    title: str
    type: str  # "story", "task", "epic" or "decision"
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
    decision_count: int = 0


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
    sprint = "sprint"
    #: The next-session note (``.project/NEXT.md``) — a document, not an
    #: item, so it has no id of its own and its events carry the literal
    #: ``NEXT``.  It exists so a write to the note is auditable in the
    #: activity log without pretending the note is a backlog item: the
    #: indexer, the audit and search all skip it deliberately (US-PM-28).
    note = "note"
    #: An open question the project needs answered (US-PM-63), stored under
    #: ``.project/decisions/`` with :class:`DecisionFrontmatter`.
    decision = "decision"


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
