"""CRUD operations for stories and tasks via python-frontmatter."""

import logging
import os
import subprocess
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import frontmatter

import yaml

from projectman.deps import detect_cycle

logger = logging.getLogger(__name__)

# Module-level cache: keyed by (base_dir, item_type) where item_type is
# "stories", "tasks", or "epics".  Values are lists of (frontmatter, body)
# tuples.  Populated on first list call; get methods extract from here first.
_cache: dict[tuple[str, str], list[tuple]] = {}

# Track when each cache entry was last populated (mtime of newest file at populate time)
_cache_mtimes: dict[tuple[str, str], tuple[float, int]] = {}

# Cache statistics — only tracked when PROJECTMAN_CACHE_DEBUG is set.
_cache_stats: dict[str, int] = {"hits": 0, "misses": 0, "invalidations": 0}
_cache_debug: bool = bool(os.environ.get("PROJECTMAN_CACHE_DEBUG"))

# Maximum stored length of a run-log note, in characters.  Notes longer than
# this are truncated server-side (never rejected) — an oversized note must
# never cost the caller the status/outcome write that came with it.
#
# Cap chosen from measured telemetry over 1,128 real note-bearing pm_update /
# pm_done_next calls: median 618, p90 1,071, p95 1,205, p99 1,529, max 2,865.
# 13.3% of those notes exceeded the old 1,024 cap; 0.27% exceed 2,048; none
# exceed 4,096.  4,096 therefore covers the entire observed distribution with
# ~1.4x headroom over the observed maximum while staying bounded.
RUN_LOG_NOTE_LIMIT = 4096


class NothingToCommit(RuntimeError):
    """There was nothing under ``.project/`` to commit.

    An *expected negative*, not a failure: the caller asked for ``.project/``
    to be committed and it already is, so the requested end-state holds.  It
    subclasses ``RuntimeError`` purely for backward compatibility — every
    existing ``except RuntimeError`` / ``pytest.raises(RuntimeError)`` around
    ``commit_project_changes`` keeps working — but its own type is what lets
    ``server.pm_commit`` tell this apart from a real commit failure *without*
    matching on the message text.  See ``server._expected_negative``.
    """


def truncate_run_log_note(
    note: str | None, limit: int = RUN_LOG_NOTE_LIMIT
) -> tuple[str | None, bool, int]:
    """Clamp a run-log note to ``limit`` characters, marking what was dropped.

    Returns ``(note, was_truncated, dropped_chars)``.  ``None`` and notes that
    already fit pass through untouched.  When truncation happens the returned
    string is exactly ``limit`` characters or fewer *including* the visible
    ``...[truncated N chars]`` marker, and ``N`` is the true number of dropped
    characters (the marker length is solved for as a fixed point, since the
    digit count of ``N`` feeds back into how much room the marker needs).
    """
    if note is None:
        return None, False, 0
    if limit <= 0:
        return "", bool(note), len(note)
    if len(note) <= limit:
        return note, False, 0

    dropped = len(note) - limit
    keep = 0
    for _ in range(8):
        marker = f"...[truncated {dropped} chars]"
        if len(marker) >= limit:
            # Pathologically small cap: no room for a marker, hard-cut instead.
            return note[:limit], True, len(note) - limit
        keep = limit - len(marker)
        new_dropped = len(note) - keep
        if new_dropped == dropped:
            break
        dropped = new_dropped
    return f"{note[:keep]}...[truncated {dropped} chars]", True, dropped


# --- Auto-generated acceptance-criterion test tasks ---------------------
#
# One test task is generated per acceptance criterion.  Both the creation path
# (``Store.create_story``) and the reconciliation path (``Store.update``) go
# through the three helpers below so the two can never drift apart.
#
# The generated *body* doubles as the association between a task and the
# criterion it came from: ``criterion_from_test_task_body`` is the exact
# inverse of ``generate_test_task_body``, so the criterion text a task was generated
# from can always be recovered from the task itself.  No frontmatter field is
# needed, which means tasks written by every prior version of ProjectMan are
# recognised on equal footing with new ones.

TEST_TASK_TITLE_LIMIT = 120

# The generated body's fixed opening.  The criterion follows the ``"> "``
# blockquote marker and runs to the end of the body (or to the end marker
# below, when one is needed).
TEST_TASK_BODY_HEADER = "Verify acceptance criterion for story {story_id}:\n\n>"

# US-PM-5-8.  ``frontmatter.dumps``/``loads`` strip trailing whitespace from
# the content they write and read back, so a criterion that is blank or ends
# in whitespace does *not* survive the trip to disk: ``"> "`` collapses to
# ``">"``, the parser stops recognising the task as auto-generated, and every
# subsequent reconciliation adds another duplicate for the same criterion.
#
# The fix is an explicit end marker appended only when the body would
# otherwise end in whitespace.  It is an HTML comment, so it is invisible in
# every markdown renderer, and it is absent from the overwhelmingly common
# case, so an ordinary test task's body is byte-for-byte what it always was.
TEST_TASK_BODY_END_MARKER = "\n\n<!-- end acceptance criterion -->"


def generate_test_task_title(criterion: str) -> str:
    """Return the auto-generated test-task title for *criterion*."""
    title = f"Test: {criterion}"
    if len(title) > TEST_TASK_TITLE_LIMIT:
        title = title[: TEST_TASK_TITLE_LIMIT - 3] + "..."
    return title


def generate_test_task_body(story_id: str, criterion: str) -> str:
    """Return the auto-generated test-task body for *criterion*.

    The result always round-trips: ``criterion_from_test_task_body`` recovers
    *criterion* exactly, both from this string and from what it becomes after
    a write/read cycle through ``frontmatter`` — including for blank,
    whitespace-only and trailing-whitespace criteria, which the serialiser
    would otherwise silently truncate.
    """
    body = f"{TEST_TASK_BODY_HEADER.format(story_id=story_id)} {criterion}"
    if body != body.rstrip():
        body += TEST_TASK_BODY_END_MARKER
    return body


def criterion_similarity(a: str, b: str) -> float:
    """How likely it is that *b* is *a* after an edit, in ``0.0..1.0``.

    ``difflib``'s plain ratio alone punishes short criteria unfairly —
    appending three words to a five-character criterion drops it below any
    useful threshold even though it is obviously the same criterion reworded.
    So the score is the better of the plain ratio and the longest shared run
    of characters measured against the *shorter* string, which makes "extended
    in place" and "trimmed in place" edits score high regardless of length.
    """
    if not a or not b:
        return 1.0 if a == b else 0.0
    matcher = SequenceMatcher(None, a, b)
    longest = matcher.find_longest_match(0, len(a), 0, len(b)).size
    return max(matcher.ratio(), longest / min(len(a), len(b)))


def criterion_from_test_task_body(story_id: str, body: str) -> Optional[str]:
    """Recover the criterion a test-task body was generated from.

    Returns ``None`` when *body* is not in the generated shape — that is the
    marker for "this task is not an auto-generated test task", so hand-written
    tasks (and test tasks whose body a human has rewritten) are never touched
    by reconciliation.

    Exact inverse of :func:`generate_test_task_body`, and tolerant of what the
    serialiser used to leave on disk before US-PM-5-8: a body already trimmed
    down to a bare ``">"`` is a blank criterion's task, not an unrecognised
    one, so pre-existing duplicates stop breeding as soon as this ships.
    """
    header = TEST_TASK_BODY_HEADER.format(story_id=story_id)
    if not body.startswith(header):
        return None
    rest = body[len(header) :]

    # Both readings of the tail are tried — "the end marker is ours" and "the
    # end marker is part of the criterion text" — and the one that regenerates
    # *body* byte-for-byte wins.  That keeps the pair exact inverses even for
    # a criterion that itself ends in the marker's text.
    candidates = []
    if rest.endswith(TEST_TASK_BODY_END_MARKER):
        candidates.append(rest[: -len(TEST_TASK_BODY_END_MARKER)])
    candidates.append(rest)
    for candidate in candidates:
        if candidate and not candidate.startswith(" "):
            continue
        criterion = candidate[1:] if candidate else ""
        if generate_test_task_body(story_id, criterion) == body:
            return criterion

    # Legacy on-disk shape, written before the end marker existed: the
    # serialiser stripped the trailing whitespace the body used to end in.
    # A bare ">" is a blank criterion's task, not an unrecognised one — so
    # pre-existing duplicates stop breeding as soon as this ships, and the
    # next reconciliation rewrites the body into the round-tripping form.
    if rest == "":
        return ""
    if rest.startswith(" "):
        return rest[1:]
    return None


# --- Removal policy for orphaned test tasks (US-PM-5-6) -----------------
#
# An "orphan" is an auto-generated test task whose criterion no longer appears
# in the story.  The policy is: NEVER delete.  Archive the ones nothing has
# happened to; leave the rest exactly where they are and flag them.
#
# Why not delete the untouched ones, as originally proposed:
#
# * The criterion text survives nowhere else.  Once the story's
#   ``acceptance_criteria`` list drops an entry, the task body is the only
#   remaining record that the criterion was ever agreed.  Deleting the task
#   destroys that record with no undo.
# * US-PM-16 established that archiving a task is not deletion — it sets an
#   orthogonal ``archived`` flag and preserves the status the work really
#   reached.  Archiving already gives us everything deletion was wanted for
#   (out of the board, out of burndown, out of "incomplete tasks on a done
#   story") at none of its cost, and ``Store.unarchive`` reverses it.
# * The matcher this policy sits on is a heuristic with documented failure
#   modes — a criterion reworded past ``CRITERION_EDIT_SIMILARITY`` is
#   reported as an orphan plus a brand-new task.  Under a delete policy that
#   misfire is unrecoverable data loss on an ordinary typo fix.  Under an
#   archive policy it is one ``Store.unarchive`` away.
#
# So the proposal is accepted in shape (untouched vs. touched) and rejected in
# its destructive half: "delete when untouched" becomes "archive when
# untouched".  Nothing this module does removes a file.
ORPHAN_ACTION_ARCHIVE = "archive"
ORPHAN_ACTION_FLAG = "flag"


def clear_all_caches() -> None:
    """Clear the entire module-level cache and reset stats."""
    _cache.clear()
    _cache_mtimes.clear()
    _cache_stats["hits"] = 0
    _cache_stats["misses"] = 0
    _cache_stats["invalidations"] = 0


def get_cache_stats() -> dict[str, int]:
    """Return a copy of the current cache statistics."""
    return dict(_cache_stats)


from .config import load_config
from .models import (
    ChangesetEntry,
    ChangesetFrontmatter,
    ChangesetStatus,
    EventType,
    ItemType,
    LogEntry,
    LogSource,
    Outcome,
    ProjectConfig,
    EpicFrontmatter,
    EpicStatus,
    Priority,
    RunLogEntry,
    SprintFrontmatter,
    SprintStatus,
    StoryFrontmatter,
    StoryStatus,
    TaskFrontmatter,
    TaskStatus,
    is_archived,
)


class Store:
    """File-backed store for stories and tasks."""

    def __init__(self, root: Path, project_dir: Path | None = None):
        self.root = root
        self.project_dir = (
            project_dir if project_dir is not None else (root / ".project")
        )
        self.stories_dir = self.project_dir / "stories"
        self.tasks_dir = self.project_dir / "tasks"
        self.epics_dir = self.project_dir / "epics"
        self.config = load_config(root) if project_dir is None else self._load_config()
        # Truncation record for the most recent update() that carried a note.
        # None until an update with a note runs.  Read by the MCP layer so the
        # response can tell the caller their note was clamped.
        self.last_note_truncation: dict | None = None
        # Result of the most recent acceptance-criteria/test-task
        # reconciliation performed by update().  None until a story update
        # actually changes acceptance_criteria.  Its "orphaned" bucket is the
        # hand-off point for the removal policy (US-PM-5-6).
        self.last_criteria_reconciliation: dict | None = None

    def _load_config(self) -> ProjectConfig:
        """Load config.yaml from self.project_dir."""
        config_path = self.project_dir / "config.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return ProjectConfig(**data)

    def _save_config(self) -> None:
        """Save config.yaml to self.project_dir."""
        config_path = self.project_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(self.config.model_dump(), f, default_flow_style=False)

    def _next_story_id(self) -> str:
        sid = f"US-{self.config.prefix}-{self.config.next_story_id}"
        self.config.next_story_id += 1
        self._save_config()
        return sid

    def _next_task_id(self, story_id: str) -> str:
        existing = self.list_tasks(story_id=story_id)
        next_num = len(existing) + 1
        return f"{story_id}-{next_num}"

    def _story_path(self, story_id: str) -> Path:
        return self.stories_dir / f"{story_id}.md"

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.md"

    def _next_epic_id(self) -> str:
        eid = f"EPIC-{self.config.prefix}-{self.config.next_epic_id}"
        self.config.next_epic_id += 1
        self._save_config()
        return eid

    def _epic_path(self, epic_id: str) -> Path:
        return self.epics_dir / f"{epic_id}.md"

    def _is_epic_id(self, item_id: str) -> bool:
        return item_id.startswith("EPIC-")

    def _is_task_id(self, item_id: str) -> bool:
        """Task IDs have 3 parts (PREFIX-N-N), story IDs have 2 (PREFIX-N)."""
        parts = item_id.split("-")
        return len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit()

    def _auto_commit(self, files: list[Path], message: str) -> None:
        """Auto-commit specific files if auto_commit is enabled.

        Silently skips if git is not available, not in a repo, or commit fails.
        """
        if not self.config.auto_commit:
            return

        import subprocess

        try:
            str_files = [str(f) for f in files if f.exists()]
            if not str_files:
                return

            result = subprocess.run(
                ["git", "add", "--"] + str_files,
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("auto-commit: git add failed: %s", result.stderr.strip())
                return

            # Check if there's anything staged
            diff = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(self.root),
                capture_output=True,
            )
            if diff.returncode == 0:
                return  # nothing staged

            commit = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if commit.returncode != 0:
                logger.warning("auto-commit: commit failed: %s", commit.stderr.strip())
                return

            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if sha.returncode == 0:
                logger.debug("auto-commit: %s [%s]", message, sha.stdout.strip())
        except FileNotFoundError:
            logger.warning("auto-commit: git not found, skipping")
        except Exception as exc:
            logger.warning("auto-commit: unexpected error: %s", exc)

    def _resolve_actor(self) -> str:
        """Resolve the actor for activity log entries.

        Priority: PROJECTMAN_ACTOR env var > git config user.name > "unknown".
        """
        env_actor = os.environ.get("PROJECTMAN_ACTOR")
        if env_actor:
            return env_actor
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except FileNotFoundError:
            pass
        return "unknown"

    def _emit_log(
        self,
        event_type: EventType,
        item_id: str,
        item_type: ItemType,
        changes: dict | None = None,
    ) -> None:
        """Emit an activity log entry. Failures are silently swallowed."""
        from .activity_log import append_log_entry

        try:
            entry = LogEntry(
                event_type=event_type,
                item_id=item_id,
                item_type=item_type,
                changes=changes or {},
                timestamp=datetime.now(timezone.utc),
                actor=self._resolve_actor(),
                source=LogSource.cli,
            )
            log_path = self.project_dir / "activity.jsonl"
            append_log_entry(log_path, entry)
        except Exception:
            logger.debug("activity log: failed to emit %s for %s", event_type, item_id)

    def _append_run_log(
        self,
        item_id: str,
        outcome: str | Outcome,
        note: str,
        status: str | None = None,
    ) -> None:
        """Append a run-log entry for an item. Failures are silently swallowed."""
        import json as _json

        try:
            logs_dir = self.project_dir / "logs"
            logs_dir.mkdir(exist_ok=True)
            entry = RunLogEntry(
                timestamp=datetime.now(timezone.utc),
                outcome=Outcome(outcome),
                status=status,
                note=note,
                actor=self._resolve_actor(),
            )
            log_path = logs_dir / f"{item_id}.jsonl"
            with open(log_path, "a") as f:
                f.write(entry.model_dump_json() + "\n")
                f.flush()
        except Exception:
            logger.debug("run log: failed to append for %s", item_id)

    def _index_embedding(
        self, item_id: str, title: str, item_type: str, body: str
    ) -> None:
        """Index or re-index an item in the embedding store.

        Silently skips if embeddings are not available (fastembed not installed).
        Only indexes stories and tasks (epics are not indexed).
        """
        if item_type not in ("story", "task"):
            return
        try:
            from .embeddings import EmbeddingStore

            emb_store = EmbeddingStore(self.project_dir)
            emb_store.index_item(item_id, title, item_type, body)
        except (ImportError, Exception):
            pass

    def get_run_log(
        self,
        item_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[RunLogEntry]:
        """Read run-log entries for an item, most recent first."""
        import json as _json

        log_path = self.project_dir / "logs" / f"{item_id}.jsonl"
        if not log_path.exists():
            return []
        entries: list[RunLogEntry] = []
        for line in log_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(RunLogEntry.model_validate_json(line))
            except Exception:
                logger.debug("run log: skipping malformed line in %s", item_id)
        entries.reverse()
        return entries[offset : offset + limit]

    def create_story(
        self,
        title: str,
        description: str,
        priority: Optional[str] = None,
        points: Optional[int] = None,
        tags: Optional[list[str]] = None,
        acceptance_criteria: Optional[list[str]] = None,
        depends_on: Optional[list[str]] = None,
    ) -> tuple[StoryFrontmatter, list["TaskFrontmatter"]]:
        """Create a new story and write it to disk.

        Returns a tuple of (story_meta, auto_created_test_tasks).
        If *acceptance_criteria* are provided, a test task is created for each.
        """
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        story_id = self._next_story_id()
        deps = depends_on or []

        self._validate_story_depends_on(story_id, deps)

        today = date.today()

        meta = StoryFrontmatter(
            id=story_id,
            title=title,
            status=StoryStatus.backlog,
            priority=Priority(priority) if priority else Priority.should,
            points=points,
            tags=tags or [],
            acceptance_criteria=acceptance_criteria or [],
            depends_on=deps,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._story_path(story_id).write_text(frontmatter.dumps(post))
        self._cache_append("stories", meta, description)
        self._emit_log(EventType.create, story_id, ItemType.story)
        self._index_embedding(story_id, title, "story", description)

        # Auto-create test tasks for each acceptance criterion
        test_tasks: list[TaskFrontmatter] = []
        for criterion in acceptance_criteria or []:
            task_title = generate_test_task_title(criterion)
            task_desc = generate_test_task_body(story_id, criterion)
            task_meta = self.create_task(story_id, task_title, task_desc, _batch=True)
            test_tasks.append(task_meta)

        files = [self._story_path(story_id), self.project_dir / "config.yaml"]
        files.extend(self._task_path(t.id) for t in test_tasks)
        self._auto_commit(files, f"pm: create {story_id}")

        return meta, test_tasks

    # --- Acceptance-criterion / test-task reconciliation -----------------

    # Below this ratio two criterion texts are considered different criteria
    # rather than an edit of the same one.  0.6 is difflib's own "close
    # enough" convention (``get_close_matches`` default cutoff).
    CRITERION_EDIT_SIMILARITY = 0.6

    def _test_tasks_for_story(
        self, story_id: str, archived: Optional[bool] = False
    ) -> list[tuple[TaskFrontmatter, str]]:
        """Return ``(meta, generated_criterion)`` for the story's test tasks.

        A task counts as auto-generated only if its *body* still has the
        generated shape (see :func:`criterion_from_test_task_body`).  Anything
        a human wrote, or a test task whose body a human has rewritten, is
        invisible here and therefore never modified.

        Archived tasks are excluded by default: an archived test task has been
        deliberately taken out of the working set, and silently rewriting it
        to a new criterion would resurrect it.  ``archived=True`` asks for
        only the archived ones (what :meth:`detect_criteria_drift` uses to
        avoid reporting a criterion whose test task was retired on purpose)
        and ``archived=None`` for both.

        Ordered by task number so positional reasoning is stable (the plain
        filename sort puts ``-10`` before ``-2``).
        """
        result: list[tuple[TaskFrontmatter, str]] = []
        for meta in self.list_tasks(story_id=story_id, archived=archived):
            try:
                _, body = self.get_task(meta.id)
            except FileNotFoundError:
                continue
            criterion = criterion_from_test_task_body(story_id, body)
            if criterion is None:
                continue
            result.append((meta, criterion))

        def _num(item: tuple[TaskFrontmatter, str]) -> int:
            tail = item[0].id.rsplit("-", 1)[-1]
            return int(tail) if tail.isdigit() else 0

        result.sort(key=_num)
        return result

    def plan_criteria_reconciliation(
        self, story_id: str, new_criteria: list[str]
    ) -> dict:
        """Work out how the story's test tasks map onto *new_criteria*.

        Pure: reads only, writes nothing.  Returns a dict with four buckets::

            {
              "unchanged": [{"task_id", "criterion"}],
              "resync":    [{"task_id", "old_criterion", "criterion",
                             "title", "retitle"}],
              "create":    [{"criterion", "index"}],
              "retired":   [{"criterion", "index", "task_id",
                             "old_criterion"}],
              "orphaned":  [{"task_id", "criterion", "status", "assignee",
                             "archived", "has_work", "work_reasons",
                             "action"}],
            }

        ``retired`` is a criterion that *would* be created except that an
        **archived** test task already covers it.  Nothing is done to it: the
        archived task is left archived and no new task is made.  See pass 3
        below for why.

        ``orphaned`` carries the US-PM-5-6 removal policy verdict for each
        test task that no longer corresponds to any criterion:

        ``action``
            ``"archive"`` when nothing has happened to the task, ``"flag"``
            when something has.  See :func:`ORPHAN_ACTION_ARCHIVE` /
            :func:`ORPHAN_ACTION_FLAG` and the module comment for why the
            untouched branch archives rather than deletes.
        ``work_reasons``
            The machine-readable reasons the task counts as touched — an
            empty list is exactly ``action == "archive"``.  A caller branches
            on these codes; it never parses a sentence.
        ``has_work``
            ``bool(work_reasons)``, kept for callers written against 5-5.

        This method stays pure — it decides, it does not act.
        :meth:`_reconcile_criteria_tasks` is what applies the verdict.

        Matching strategy, two passes:

        1. **Identity.** A criterion whose exact text a task was generated
           from keeps that task.  Position is irrelevant, so reordering
           criteria and inserting into the middle are both free.
        2. **Similarity.** Whatever is left over is matched greedily,
           best-ratio-first, by :func:`criterion_similarity` above
           ``CRITERION_EDIT_SIMILARITY``.  This is what recognises "the same
           criterion, reworded" and drives the title/body resync.
        3. **Archived coverage.** Whatever is *still* left over is checked,
           by exact text only, against the story's **archived** test tasks.
           A hit is diverted from ``create`` into ``retired`` and nothing
           happens to it (US-PM-5-9).

        Pass 3 exists because archiving is not deletion and not completion
        (US-PM-16); it is the recoverable resting place a human — or the
        US-PM-5-6 orphan policy — chose for a test task, and
        :meth:`unarchive` is what reverses it.  Without pass 3 a live
        criterion whose test task was archived sat in ``create`` forever, so
        *any* unrelated edit to the criteria list minted a second live task
        quoting a criterion the story already had.  Silently un-archiving
        instead would be the same overreach in the other direction: it
        undoes a deliberate decision without asking.  So the reconciler
        declines to act, and the record says so, leaving ``pm_restore`` as
        the explicit way back.  This also keeps the pass in step with
        :meth:`detect_criteria_drift`, which has always suppressed exactly
        these criteria — see the contract in that docstring.

        Known failure modes, stated honestly:

        * A criterion rewritten past the similarity threshold reads as a
          delete plus an add: a new task is created and the old one is
          reported as orphaned.  Nothing is lost, but the history splits.
        * Deleting one criterion while heavily editing another in the *same*
          call can pair the surviving edit against the deleted criterion's
          task when the two texts are similar.  Greedy best-first ordering
          makes the most-similar pair win, which limits but does not
          eliminate this.
        * Duplicate identical criteria are matched arbitrarily among
          themselves.  Harmless: the texts are identical.
        * Swapping the text of two criteria in place is seen as "no change",
          since both texts still exist.  The task-to-criterion association
          flips but every task still quotes a live criterion.
        """
        tasks = self._test_tasks_for_story(story_id)
        claimed: set[str] = set()
        matched: dict[int, tuple[TaskFrontmatter, str]] = {}

        # Pass 1 — identity.
        for i, criterion in enumerate(new_criteria):
            for meta, old_criterion in tasks:
                if meta.id in claimed:
                    continue
                if old_criterion == criterion:
                    matched[i] = (meta, old_criterion)
                    claimed.add(meta.id)
                    break

        # Pass 2 — similarity, greedy best-first over what is left.
        candidates: list[tuple[float, int, str, TaskFrontmatter, str]] = []
        for i, criterion in enumerate(new_criteria):
            if i in matched:
                continue
            for meta, old_criterion in tasks:
                if meta.id in claimed:
                    continue
                ratio = criterion_similarity(old_criterion, criterion)
                if ratio >= self.CRITERION_EDIT_SIMILARITY:
                    candidates.append((ratio, i, meta.id, meta, old_criterion))
        # Sort by descending ratio, then by criterion index and task id so the
        # outcome is deterministic when ratios tie.
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        for _ratio, i, task_id, meta, old_criterion in candidates:
            if i in matched or task_id in claimed:
                continue
            matched[i] = (meta, old_criterion)
            claimed.add(task_id)

        # Pass 3 — archived coverage.  Purely a veto on ``create``: archived
        # tasks are never claimed, resynced, retitled or re-orphaned, so this
        # cannot disturb any of the buckets above.
        #
        # Identity only, deliberately — no similarity arm.  A resync is what
        # similarity buys elsewhere, and an archived task's body is never
        # rewritten, so a *reworded* criterion has no test task quoting it
        # and genuinely does need one.  The exact-text case is the only one
        # where creating would produce a literal duplicate of text an
        # existing task already carries.
        retired_tasks = self._test_tasks_for_story(story_id, archived=True)

        def _covering_archived_task(
            criterion: str,
        ) -> Optional[tuple[TaskFrontmatter, str]]:
            for meta, old_criterion in retired_tasks:
                if old_criterion == criterion:
                    return meta, old_criterion
            return None

        unchanged: list[dict] = []
        resync: list[dict] = []
        create: list[dict] = []
        retired: list[dict] = []
        for i, criterion in enumerate(new_criteria):
            if i not in matched:
                covering = _covering_archived_task(criterion)
                if covering is not None:
                    retired.append(
                        {
                            "criterion": criterion,
                            "index": i,
                            "task_id": covering[0].id,
                            "old_criterion": covering[1],
                        }
                    )
                else:
                    create.append({"criterion": criterion, "index": i})
                continue
            meta, old_criterion = matched[i]
            if old_criterion == criterion:
                unchanged.append({"task_id": meta.id, "criterion": criterion})
                continue
            # Only retitle a task whose title is still exactly what the
            # generator produced.  A human-renamed test task keeps its title;
            # its body is still resynced, because a body quoting a criterion
            # that no longer exists is the bug this whole story is about.
            retitle = meta.title == generate_test_task_title(old_criterion)
            resync.append(
                {
                    "task_id": meta.id,
                    "old_criterion": old_criterion,
                    "criterion": criterion,
                    "title": generate_test_task_title(criterion) if retitle else meta.title,
                    "retitle": retitle,
                }
            )

        orphaned = []
        for meta, old_criterion in tasks:
            if meta.id in claimed:
                continue
            reasons = self._orphan_work_reasons(meta, old_criterion)
            orphaned.append(
                {
                    "task_id": meta.id,
                    "criterion": old_criterion,
                    "status": meta.status.value
                    if hasattr(meta.status, "value")
                    else str(meta.status),
                    "assignee": meta.assignee,
                    "archived": meta.archived,
                    "has_work": bool(reasons),
                    "work_reasons": reasons,
                    "action": ORPHAN_ACTION_FLAG if reasons else ORPHAN_ACTION_ARCHIVE,
                }
            )

        return {
            "unchanged": unchanged,
            "resync": resync,
            "create": create,
            "retired": retired,
            "orphaned": orphaned,
        }

    def detect_criteria_drift(
        self, story_id: str, criteria: Optional[list[str]] = None
    ) -> dict:
        """Report acceptance-criteria / test-task drift for one story.

        US-PM-5-7.  Pure — reads only, decides nothing, changes nothing.
        Returns::

            {
              "missing": [{"criterion", "index"}],   # criterion, no test task
              "stale":   [{"task_id", "criterion"}],  # test task, dead quote
            }

        This is deliberately a thin projection of
        :meth:`plan_criteria_reconciliation` rather than a second matcher.
        pm_audit and the reconciler must never disagree about what counts as
        a match: if the audit reports drift the reconciler cannot see, a
        caller is told to fix something that no ``pm_update`` will fix.

        * ``missing`` is the plan's ``create`` bucket, verbatim — criteria
          that would get a brand-new test task.  A criterion an **archived**
          test task already covers is not among them: the plan itself
          diverts those into its ``retired`` bucket (US-PM-5-9), because an
          archived test task was retired on purpose (US-PM-16) and neither
          nagging about it nor re-creating it is wanted.  This filter used
          to live here instead, which is precisely how the pair came to
          disagree: the audit suppressed a criterion the reconciler still
          created, so the audit read clean right up until ``pm_update`` grew
          a duplicate.
        * ``stale`` is the plan's ``orphaned`` bucket (a test task quoting
          text with no live counterpart at all) plus its ``resync`` bucket (a
          test task whose quoted text was *edited*, so the body still quotes
          a criterion that no longer exists — the exact shape of the drift
          that prompted this check).

        A story with no criteria yields no ``missing`` — there is nothing that
        could be untested — but it can still yield ``stale``: see below.
        Hand-written tasks and human-rewritten test-task bodies are invisible
        to the matcher and so can never appear here.
        """
        if criteria is None:
            try:
                meta, _ = self.get_story(story_id)
            except FileNotFoundError:
                return {"missing": [], "stale": []}
            criteria = list(meta.acceptance_criteria or [])
        criteria = [c for c in criteria]

        plan = self.plan_criteria_reconciliation(story_id, criteria)

        # ``missing`` is defined relative to the criteria list, so an empty
        # list has none by construction (``plan["create"]`` is empty too).
        # ``stale`` is not: a live test task quoting text that no criterion
        # carries is stale whether the story has other criteria or not, and
        # when *every* criterion is removed that task is exactly the flagged
        # orphan pm_update refused to archive.  Short-circuiting on "no
        # criteria" used to drop it, so the flag died with the pm_update
        # response and no audit ever mentioned it again (US-PM-5-10).
        missing: list[dict] = [
            {"criterion": e["criterion"], "index": e["index"]}
            for e in plan["create"]
        ]
        stale = [
            {"task_id": e["task_id"], "criterion": e["criterion"]}
            for e in plan["orphaned"]
        ] + [
            {"task_id": e["task_id"], "criterion": e["old_criterion"]}
            for e in plan["resync"]
        ]
        stale.sort(key=lambda e: e["task_id"])
        return {"missing": missing, "stale": stale}

    def _has_criteria_drift(self, story_id: str, criteria: list[str]) -> bool:
        """Whether *story_id*'s test tasks disagree with *criteria*.

        The same detector pm_audit reports from, so "the audit says drifted"
        and "update will reconcile" are the same predicate.  Never raises: a
        failure to probe must not take down the caller's real update.
        """
        try:
            drift = self.detect_criteria_drift(story_id, criteria)
        except Exception:
            logger.debug("criteria drift probe failed for %s", story_id)
            return False
        return bool(drift["missing"] or drift["stale"])

    # Reason codes for "something has happened to this task".  Stable strings:
    # a caller branches on these, so they are part of the contract.
    ORPHAN_REASON_STATUS = "status-not-todo"
    ORPHAN_REASON_ASSIGNED = "assigned"
    ORPHAN_REASON_RUN_LOG = "run-log-entries"
    ORPHAN_REASON_RENAMED = "title-edited"
    ORPHAN_REASON_DEPENDS_ON = "has-dependencies"
    ORPHAN_REASON_DEPENDED_ON = "has-dependents"

    def _orphan_work_reasons(self, meta: TaskFrontmatter, criterion: str) -> list[str]:
        """Every reason an orphaned test task counts as touched, or ``[]``.

        Empty means "nothing has happened to this task since it was
        generated", which is the only state the policy will archive.  The
        definition is deliberately wider than the original proposal's
        (todo / unassigned / no run log), because each extra signal is a
        human having done something to the task:

        * ``status-not-todo`` — somebody moved it, including to ``done``.
        * ``assigned`` — somebody owns it.
        * ``run-log-entries`` — an attempt was recorded against it.
        * ``title-edited`` — the title is no longer what the generator
          produced, so a human renamed it.
        * ``has-dependencies`` / ``has-dependents`` — a human wired it into
          the dependency graph, in either direction.

        Two further "touched" states never reach this function at all, which
        is why they have no code here: a task whose *body* a human rewrote
        stops parsing as auto-generated (:func:`criterion_from_test_task_body`
        returns ``None``), and an already-archived task is excluded by
        :meth:`_test_tasks_for_story`.  Both are invisible to reconciliation
        and therefore untouchable by this policy.
        """
        reasons: list[str] = []
        status = (
            meta.status.value if hasattr(meta.status, "value") else str(meta.status)
        )
        if status != TaskStatus.todo.value:
            reasons.append(self.ORPHAN_REASON_STATUS)
        if meta.assignee:
            reasons.append(self.ORPHAN_REASON_ASSIGNED)
        if self._run_log_shows_activity(meta.id):
            reasons.append(self.ORPHAN_REASON_RUN_LOG)
        if meta.title != generate_test_task_title(criterion):
            reasons.append(self.ORPHAN_REASON_RENAMED)
        if meta.depends_on:
            reasons.append(self.ORPHAN_REASON_DEPENDS_ON)
        if any(meta.id in t.depends_on for t in self.list_tasks()):
            reasons.append(self.ORPHAN_REASON_DEPENDED_ON)
        return reasons

    def _run_log_shows_activity(self, item_id: str) -> bool:
        """Whether *item_id*'s run log is evidence that something happened.

        True when the log holds any content at all, false only for "no file"
        and "a file with nothing but whitespace in it".

        Deliberately *not* ``bool(self.get_run_log(...))``.  That reader drops
        malformed lines on the floor so one corrupt entry cannot hide the rest
        of the history — correct for display, wrong for this question, because
        a wholly corrupt log then parses as empty and reads as "never
        touched", which is how an orphan with unreadable evidence of work got
        archived instead of flagged (US-PM-5-10).  An unreadable run log is
        not evidence of absence, so every failure mode here — unparseable
        lines, undecodable bytes, an unreadable file — resolves to True and
        the task is flagged for a human rather than archived.
        """
        log_path = self.project_dir / "logs" / f"{item_id}.jsonl"
        try:
            if not log_path.exists():
                return False
            return any(line.strip() for line in log_path.read_text().splitlines())
        except Exception:
            logger.debug("run log: unreadable for %s, counting it as work", item_id)
            return True

    def _write_test_task_sync(self, task_id: str, title: str, body: str) -> Path:
        """Rewrite a test task's title and body in place.

        Deliberately not routed through :meth:`update`, which would reset
        ``last_note_truncation`` on the in-flight story update and fire a
        separate auto-commit per task.
        """
        path = self._task_path(task_id)
        post = frontmatter.load(str(path))
        old_title = post.metadata.get("title")
        old_body = post.content
        post.metadata["title"] = title
        post.metadata["updated"] = date.today().isoformat()
        post.content = body
        meta = TaskFrontmatter(**post.metadata)
        path.write_text(frontmatter.dumps(post))
        self._cache_update_entry("tasks", task_id, meta, body)
        changes: dict[str, dict] = {}
        if old_title != title:
            changes["title"] = {"before": old_title, "after": title}
        if old_body != body:
            changes["body"] = {"before": old_body, "after": body}
        self._emit_log(EventType.update, task_id, ItemType.task, changes=changes)
        self._index_embedding(task_id, title, "task", body)
        return path

    def _write_test_task_archived(self, task_id: str) -> Path:
        """Set an orphaned test task's ``archived`` flag in place.

        Title, body and status are left exactly as they were — US-PM-16's
        rule: archiving records that work was abandoned, it does not claim it
        was finished, and it does not remove anything.  ``Store.unarchive``
        puts the task straight back.

        Not routed through :meth:`update` for the same reason as
        :meth:`_write_test_task_sync`: it would clobber the in-flight story
        update's ``last_note_truncation`` and fire a per-task auto-commit.
        """
        path = self._task_path(task_id)
        post = frontmatter.load(str(path))
        was_archived = bool(post.metadata.get("archived"))
        post.metadata["archived"] = True
        post.metadata["updated"] = date.today().isoformat()
        meta = TaskFrontmatter(**post.metadata)
        path.write_text(frontmatter.dumps(post))
        self._cache_update_entry("tasks", task_id, meta, post.content)
        if not was_archived:
            self._emit_log(
                EventType.update,
                task_id,
                ItemType.task,
                changes={"archived": {"before": False, "after": True}},
            )
        return path

    def _reconcile_criteria_tasks(
        self, story_id: str, new_criteria: list[str]
    ) -> tuple[dict, list[Path]]:
        """Apply :meth:`plan_criteria_reconciliation` to disk.

        Adds a test task for every new criterion, resyncs the title and body
        of every task whose criterion was edited, and applies the US-PM-5-6
        removal policy to the orphans: those with no work against them are
        archived (never deleted — see the module comment above
        :data:`ORPHAN_ACTION_ARCHIVE`), and those with work are left
        byte-for-byte alone and reported for human attention.
        """
        plan = self.plan_criteria_reconciliation(story_id, new_criteria)
        touched: list[Path] = []

        for entry in plan["resync"]:
            body = generate_test_task_body(story_id, entry["criterion"])
            touched.append(
                self._write_test_task_sync(entry["task_id"], entry["title"], body)
            )

        created: list[str] = []
        for entry in plan["create"]:
            criterion = entry["criterion"]
            meta = self.create_task(
                story_id,
                generate_test_task_title(criterion),
                generate_test_task_body(story_id, criterion),
                _batch=True,
            )
            created.append(meta.id)
            entry["task_id"] = meta.id
            touched.append(self._task_path(meta.id))

        archived: list[str] = []
        flagged: list[str] = []
        for entry in plan["orphaned"]:
            if entry["action"] == ORPHAN_ACTION_ARCHIVE:
                touched.append(self._write_test_task_archived(entry["task_id"]))
                entry["archived"] = True
                archived.append(entry["task_id"])
            else:
                flagged.append(entry["task_id"])

        plan["created_task_ids"] = created
        # Nothing to apply for ``retired`` — declining to act is the action
        # (US-PM-5-9).  The ids are surfaced so a caller can see which
        # archived task stood in for a criterion and reach for pm_restore.
        plan["retired_task_ids"] = [e["task_id"] for e in plan["retired"]]
        plan["resynced_task_ids"] = [e["task_id"] for e in plan["resync"]]
        plan["archived_task_ids"] = archived
        plan["flagged_task_ids"] = flagged
        return plan, touched

    def get_story(self, story_id: str) -> tuple[StoryFrontmatter, str]:
        """Read a story, returning (frontmatter, body). Uses cache if populated and fresh."""
        key = self._cache_key("stories")
        if key in _cache and not self._is_cache_stale("stories"):
            for meta, body in _cache[key]:
                if meta.id == story_id:
                    if _cache_debug:
                        _cache_stats["hits"] += 1
                    return meta, body
        path = self._story_path(story_id)
        if not path.exists():
            raise FileNotFoundError(f"Story not found: {story_id}")
        post = frontmatter.load(str(path))
        meta = StoryFrontmatter(**post.metadata)
        return meta, post.content

    def _cache_key(self, item_type: str) -> tuple[str, str]:
        """Return the cache key for a given item type."""
        return (str(self.project_dir), item_type)

    def _get_dir_mtime(self, dir_path: Path) -> tuple[float, int]:
        """Return (mtime, file_count) of the most recently modified file in dir_path.

        Returns (0.0, 0) if dir_path does not exist or is empty.
        """
        if not dir_path.exists():
            return (0.0, 0)
        files = list(dir_path.glob("*.md"))
        if not files:
            return (0.0, 0)
        return (max(f.stat().st_mtime for f in files), len(files))

    def _is_cache_stale(self, item_type: str) -> bool:
        """Check if cached data for item_type is potentially stale.

        Compares stored (mtime, file_count) against current to detect
        external changes (e.g., git pull, direct edits, file deletions).
        """
        key = self._cache_key(item_type)
        if key not in _cache:
            return True

        stored = _cache_mtimes.get(key, (0.0, 0))
        if stored == (0.0, 0):
            return True

        dir_map = {
            "stories": self.stories_dir,
            "tasks": self.tasks_dir,
            "epics": self.epics_dir,
        }
        dir_path = dir_map.get(item_type)
        if not dir_path:
            return True

        current_mtime, current_count = self._get_dir_mtime(dir_path)
        stored_mtime, stored_count = stored
        return current_mtime > stored_mtime or current_count != stored_count

    def _invalidate_cache(self, item_type: str) -> None:
        """Remove cached entries for the given item type."""
        if _cache.pop(self._cache_key(item_type), None) is not None and _cache_debug:
            _cache_stats["invalidations"] += 1

    def _cache_append(self, item_type: str, meta, body: str) -> None:
        """Append a new entry to the cache.

        If cache is not yet populated, this is a no-op — the next list_* call
        will repopulate from disk which will include this item.
        """
        key = self._cache_key(item_type)
        if key not in _cache:
            return
        _cache[key].append((meta, body))

    def _cache_update_entry(
        self, item_type: str, item_id: str, meta, body: str
    ) -> None:
        """Replace a single entry in the cache if it is populated.

        If the item has transitioned to archived status, evict it from the
        cache instead of updating — archived items are excluded from the
        cache to bound memory usage.
        """
        key = self._cache_key(item_type)
        if key in _cache:
            # Check if item should be evicted (archived status)
            should_evict = (
                item_type == "stories"
                and hasattr(meta, "status")
                and meta.status == StoryStatus.archived
            ) or (
                item_type == "epics"
                and hasattr(meta, "status")
                and meta.status == EpicStatus.archived
            )
            for i, (m, _) in enumerate(_cache[key]):
                if m.id == item_id:
                    if should_evict:
                        _cache[key].pop(i)
                        if _cache_debug:
                            _cache_stats["invalidations"] += 1
                    else:
                        _cache[key][i] = (meta, body)
                    return

    def clear_cache(self) -> None:
        """Clear all cached entries for this Store instance."""
        for item_type in ("stories", "tasks", "epics"):
            _cache.pop(self._cache_key(item_type), None)

    def _read_stories_from_disk(
        self, status_filter: Optional[str] = None
    ) -> list[tuple[StoryFrontmatter, str]]:
        """Read stories from disk, optionally filtered by status."""
        if not self.stories_dir.exists():
            return []
        entries = []
        for path in sorted(self.stories_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = StoryFrontmatter(**post.metadata)
                if status_filter and meta.status.value != status_filter:
                    continue
                entries.append((meta, post.content))
            except Exception:
                continue
        return entries

    def list_stories(self, status: Optional[str] = None) -> list[StoryFrontmatter]:
        """List all stories, optionally filtered by status. Skips malformed files.

        Archived stories are excluded from the cache to bound memory usage.
        Requests for archived stories bypass the cache and read from disk.

        Cache is automatically invalidated if external file changes are detected.
        """
        if not self.stories_dir.exists():
            return []

        if status == StoryStatus.archived.value:
            entries = self._read_stories_from_disk(status_filter=status)
            return [m for m, _ in entries]

        key = self._cache_key("stories")
        if key not in _cache or self._is_cache_stale("stories"):
            if _cache_debug:
                _cache_stats["misses"] += 1
            entries = []
            for path in sorted(self.stories_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(path))
                    meta = StoryFrontmatter(**post.metadata)
                    if meta.status == StoryStatus.archived:
                        continue
                    entries.append((meta, post.content))
                except Exception:
                    continue
            _cache[key] = entries
            _cache_mtimes[key] = self._get_dir_mtime(self.stories_dir)
        else:
            if _cache_debug:
                _cache_stats["hits"] += 1
        all_entries = _cache[key]
        if status is None:
            return [m for m, _ in all_entries]
        return [m for m, _ in all_entries if m.status.value == status]

    def create_epic(
        self,
        title: str,
        description: str,
        priority: Optional[str] = None,
        target_date: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> EpicFrontmatter:
        """Create a new epic and write it to disk."""
        self.epics_dir.mkdir(parents=True, exist_ok=True)
        epic_id = self._next_epic_id()
        today = date.today()

        meta = EpicFrontmatter(
            id=epic_id,
            title=title,
            status=EpicStatus.draft,
            priority=Priority(priority) if priority else Priority.should,
            target_date=target_date,
            tags=tags or [],
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._epic_path(epic_id).write_text(frontmatter.dumps(post))
        self._cache_append("epics", meta, description)
        self._emit_log(EventType.create, epic_id, ItemType.epic)

        self._auto_commit(
            [self._epic_path(epic_id), self.project_dir / "config.yaml"],
            f"pm: create {epic_id}",
        )

        return meta

    def get_epic(self, epic_id: str) -> tuple[EpicFrontmatter, str]:
        """Read an epic, returning (frontmatter, body). Uses cache if populated and fresh."""
        key = self._cache_key("epics")
        if key in _cache and not self._is_cache_stale("epics"):
            for meta, body in _cache[key]:
                if meta.id == epic_id:
                    if _cache_debug:
                        _cache_stats["hits"] += 1
                    return meta, body
        path = self._epic_path(epic_id)
        if not path.exists():
            raise FileNotFoundError(f"Epic not found: {epic_id}")
        post = frontmatter.load(str(path))
        meta = EpicFrontmatter(**post.metadata)
        return meta, post.content

    def _read_epics_from_disk(
        self, status_filter: Optional[str] = None
    ) -> list[tuple[EpicFrontmatter, str]]:
        """Read epics from disk, optionally filtered by status."""
        if not self.epics_dir.exists():
            return []
        entries = []
        for path in sorted(self.epics_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = EpicFrontmatter(**post.metadata)
                if status_filter and meta.status.value != status_filter:
                    continue
                entries.append((meta, post.content))
            except Exception:
                continue
        return entries

    def list_epics(self, status: Optional[str] = None) -> list[EpicFrontmatter]:
        """List all epics, optionally filtered by status. Skips malformed files.

        Archived epics are excluded from the cache to bound memory usage.
        Requests for archived epics bypass the cache and read from disk.

        Cache is automatically invalidated if external file changes are detected.
        """
        if not self.epics_dir.exists():
            return []

        if status == EpicStatus.archived.value:
            entries = self._read_epics_from_disk(status_filter=status)
            return [m for m, _ in entries]

        key = self._cache_key("epics")
        if key not in _cache or self._is_cache_stale("epics"):
            if _cache_debug:
                _cache_stats["misses"] += 1
            entries = []
            for path in sorted(self.epics_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(path))
                    meta = EpicFrontmatter(**post.metadata)
                    if meta.status == EpicStatus.archived:
                        continue
                    entries.append((meta, post.content))
                except Exception:
                    continue
            _cache[key] = entries
            _cache_mtimes[key] = self._get_dir_mtime(self.epics_dir)
        else:
            if _cache_debug:
                _cache_stats["hits"] += 1
        all_entries = _cache[key]
        if status is None:
            return [m for m, _ in all_entries]
        return [m for m, _ in all_entries if m.status.value == status]

    def _validate_task_depends_on(self, task_id: str, depends_on: list[str]) -> None:
        """Validate task depends_on entries: no self-ref, all must exist.

        Cross-story task dependencies are allowed to support dependency graphs
        that span multiple stories.
        """
        if not depends_on:
            return
        for dep in depends_on:
            if dep == task_id:
                raise ValueError(f"Task cannot depend on itself: {dep}")
            # Check that the dependency exists (task or story)
            dep_task_path = self._task_path(dep)
            dep_story_path = self._story_path(dep)
            if not dep_task_path.exists() and not dep_story_path.exists():
                raise ValueError(
                    f"Dependency {dep} does not exist (not a task or story)"
                )

    def _validate_story_depends_on(self, story_id: str, depends_on: list[str]) -> None:
        """Validate story depends_on entries: no self-ref, all must exist.

        Stories can depend on other stories or tasks.
        """
        if not depends_on:
            return
        for dep in depends_on:
            if dep == story_id:
                raise ValueError(f"Story cannot depend on itself: {dep}")
            # Check that the dependency exists (story or task)
            dep_story_path = self._story_path(dep)
            dep_task_path = self._task_path(dep)
            if not dep_story_path.exists() and not dep_task_path.exists():
                raise ValueError(
                    f"Dependency {dep} does not exist (not a story or task)"
                )

    def create_task(
        self,
        story_id: str,
        title: str,
        description: str,
        points: Optional[int] = None,
        tags: Optional[list[str]] = None,
        depends_on: Optional[list[str]] = None,
        *,
        _batch: bool = False,
    ) -> TaskFrontmatter:
        """Create a new task under a story."""
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        # Verify story exists
        if not self._story_path(story_id).exists():
            raise FileNotFoundError(f"Story not found: {story_id}")

        task_id = self._next_task_id(story_id)
        deps = depends_on or []

        self._validate_task_depends_on(task_id, deps)

        today = date.today()

        meta = TaskFrontmatter(
            id=task_id,
            story_id=story_id,
            title=title,
            status=TaskStatus.todo,
            points=points,
            tags=tags or [],
            depends_on=deps,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._task_path(task_id).write_text(frontmatter.dumps(post))
        self._cache_append("tasks", meta, description)
        self._emit_log(EventType.create, task_id, ItemType.task)
        self._index_embedding(task_id, title, "task", description)

        if not _batch:
            self._auto_commit([self._task_path(task_id)], f"pm: create {task_id}")

        return meta

    def create_tasks(
        self,
        story_id: str,
        tasks: list[dict],
    ) -> list[TaskFrontmatter]:
        """Create multiple tasks under a story in a single call.

        Each entry in *tasks* should be a dict with keys ``title``,
        ``description``, and optionally ``points``, ``tags``, and
        ``depends_on``.  Returns the list of created
        :class:`TaskFrontmatter` objects.

        Dependencies are validated per-entry (self-ref, existence or
        intra-batch reference, sibling check) and a post-batch cycle
        check runs after all tasks are written.  On cycle detection the
        batch is rolled back.
        """
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        if not self._story_path(story_id).exists():
            raise FileNotFoundError(f"Story not found: {story_id}")

        # Pre-compute IDs for the entire batch so we can allow
        # forward references (task B depends on task C created later
        # in the same batch).
        batch_ids: list[str] = []
        cur = self._next_task_id(story_id)
        for i, _ in enumerate(tasks):
            if i == 0:
                batch_ids.append(cur)
            else:
                # Simulate sequential ID assignment.
                parts = cur.rsplit("-", 1)
                cur = f"{parts[0]}-{int(parts[1]) + 1}"
                batch_ids.append(cur)
        batch_id_set = set(batch_ids)

        today = date.today()
        created: list[TaskFrontmatter] = []

        for entry, task_id in zip(tasks, batch_ids):
            deps = entry.get("depends_on", [])

            # Validate deps: self-ref and non-batch deps via the
            # standard validator; batch-internal deps just need a
            # self-ref check (existence is guaranteed once we write).
            for dep in deps:
                if dep == task_id:
                    raise ValueError(f"Task cannot depend on itself: {dep}")
                if dep not in batch_id_set:
                    # Delegate to the standard validator for the single dep.
                    self._validate_task_depends_on(task_id, [dep])

            meta = TaskFrontmatter(
                id=task_id,
                story_id=story_id,
                title=entry["title"],
                status=TaskStatus.todo,
                points=entry.get("points"),
                tags=entry.get("tags", []),
                depends_on=deps,
                created=today,
                updated=today,
            )
            post = frontmatter.Post(
                content=entry.get("description", ""),
                **meta.model_dump(mode="json"),
            )
            self._task_path(task_id).write_text(frontmatter.dumps(post))
            self._cache_append("tasks", meta, entry.get("description", ""))
            self._emit_log(EventType.create, task_id, ItemType.task)
            created.append(meta)

        # Post-batch cycle check — rollback on failure.
        if created:
            try:
                self._check_dependency_cycles(story_id)
            except ValueError:
                for task in created:
                    self._task_path(task.id).unlink(missing_ok=True)
                self._invalidate_cache("tasks")
                raise

            files = [self._task_path(t.id) for t in created]
            self._auto_commit(
                files, f"pm: create {len(created)} tasks under {story_id}"
            )

        return created

    def _check_dependency_cycles(self, story_id: str) -> None:
        """Detect dependency cycles among all tasks in a story via DFS."""
        all_tasks = self.list_tasks(story_id=story_id)
        graph: dict[str, list[str]] = {t.id: list(t.depends_on) for t in all_tasks}

        cycle = detect_cycle(graph)
        if cycle is not None:
            path = " -> ".join(cycle)
            raise ValueError(f"Dependency cycle detected: {path}")

    def get_task(self, task_id: str) -> tuple[TaskFrontmatter, str]:
        """Read a task, returning (frontmatter, body). Uses cache if populated and fresh."""
        key = self._cache_key("tasks")
        if key in _cache and not self._is_cache_stale("tasks"):
            for meta, body in _cache[key]:
                if meta.id == task_id:
                    if _cache_debug:
                        _cache_stats["hits"] += 1
                    return meta, body
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        post = frontmatter.load(str(path))
        meta = TaskFrontmatter(**post.metadata)
        return meta, post.content

    def list_tasks(
        self,
        story_id: Optional[str] = None,
        status: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> list[TaskFrontmatter]:
        """List tasks, optionally filtered by story and/or status. Skips malformed files.

        Args:
            archived: ``None`` (default) returns archived and active tasks
                alike — the historical behaviour.  ``False`` returns only
                active tasks, ``True`` only archived ones.

        Cache is automatically invalidated if external file changes are detected.
        """
        if not self.tasks_dir.exists():
            return []
        key = self._cache_key("tasks")
        if key not in _cache or self._is_cache_stale("tasks"):
            if _cache_debug:
                _cache_stats["misses"] += 1
            entries = []
            for path in sorted(self.tasks_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(path))
                    meta = TaskFrontmatter(**post.metadata)
                    entries.append((meta, post.content))
                except Exception:
                    continue
            _cache[key] = entries
            _cache_mtimes[key] = self._get_dir_mtime(self.tasks_dir)
        else:
            if _cache_debug:
                _cache_stats["hits"] += 1
        all_entries = _cache[key]
        result = all_entries
        if story_id:
            result = [(m, b) for m, b in result if m.story_id == story_id]
        if status:
            result = [(m, b) for m, b in result if m.status.value == status]
        if archived is not None:
            result = [(m, b) for m, b in result if m.archived is archived]
        return [m for m, _ in result]

    def list_all(
        self,
        item_type: str,
    ) -> list[dict]:
        """Return all items of a type with full data (frontmatter + body).

        Args:
            item_type: One of "epics", "stories", or "tasks".

        Returns a list of dicts, each containing model_dump + body.
        """
        if item_type == "epics":
            # Populate cache via list_epics
            self.list_epics()
        elif item_type == "stories":
            self.list_stories()
        elif item_type == "tasks":
            self.list_tasks()
        else:
            raise ValueError(
                f"Unknown item type: {item_type}. Use: epics, stories, tasks"
            )

        key = self._cache_key(item_type)
        entries = _cache.get(key, [])
        results = []
        for meta, body in entries:
            item = meta.model_dump(mode="json")
            item["body"] = body
            results.append(item)
        return results

    def _read_tasks_from_disk(
        self,
        story_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> list[tuple[TaskFrontmatter, str]]:
        """Read tasks from disk, optionally filtered by story and/or status.

        ``archived`` defaults to ``None`` (no filtering); pass ``False`` for
        only-active or ``True`` for only-archived tasks.

        Always reads from disk, bypassing cache entirely.
        """
        if not self.tasks_dir.exists():
            return []
        entries = []
        for path in sorted(self.tasks_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = TaskFrontmatter(**post.metadata)
                if story_id and meta.story_id != story_id:
                    continue
                if status_filter and meta.status.value != status_filter:
                    continue
                if archived is not None and meta.archived is not archived:
                    continue
                entries.append((meta, post.content))
            except Exception:
                continue
        return entries

    def update(
        self, item_id: str, **kwargs
    ) -> EpicFrontmatter | StoryFrontmatter | TaskFrontmatter:
        """Update fields on an epic, story, or task.

        Accepts frontmatter fields as keyword arguments.  The special
        ``body`` kwarg replaces the markdown body content (not frontmatter).
        """
        is_epic = self._is_epic_id(item_id)
        is_task = not is_epic and self._is_task_id(item_id)
        is_story = not is_epic and not is_task

        if is_epic:
            path = self._epic_path(item_id)
        elif is_task:
            path = self._task_path(item_id)
        else:
            path = self._story_path(item_id)

        if not path.exists():
            raise FileNotFoundError(f"Item not found: {item_id}")

        post = frontmatter.load(str(path))

        # Capture before-state for activity log diffs
        old_body = post.content
        old_meta = dict(post.metadata)

        # Empty-string assignee means "unassign" (MCP optional params can't
        # express None-as-a-value); applied to metadata directly below.
        unassign = kwargs.get("assignee") == ""
        if unassign:
            kwargs["assignee"] = None

        # Capture field info for auto-commit message before modifying kwargs
        commit_parts = []
        for k, v in kwargs.items():
            if v is not None:
                commit_parts.append(f"{k}={v}" if k != "body" else "body")
        if unassign:
            commit_parts.append("assignee=none")

        # Pop run-log fields — they don't go into frontmatter
        outcome = kwargs.pop("outcome", None)
        note = kwargs.pop("note", None)

        # An oversized note is truncated, never rejected.  Raising here would
        # take the status/outcome write down with it — a caller that only
        # checks is_error would silently lose the state change.
        self.last_note_truncation = None
        if note is not None:
            original_length = len(note)
            note, was_truncated, dropped = truncate_run_log_note(note)
            self.last_note_truncation = {
                "truncated": was_truncated,
                "original_length": original_length,
                "stored_length": len(note),
                "dropped_chars": dropped,
                "limit": RUN_LOG_NOTE_LIMIT,
            }
            if was_truncated:
                logger.warning(
                    "run log: truncated note for %s (%d chars, dropped %d)",
                    item_id,
                    original_length,
                    dropped,
                )
        if outcome is not None:
            Outcome(outcome)  # validate enum value

        # Handle body separately — it replaces markdown content, not metadata
        new_body = kwargs.pop("body", None)
        if new_body is not None:
            post.content = new_body

        # Validate depends_on before applying to task or story
        new_depends_on = kwargs.get("depends_on")
        if new_depends_on is not None:
            if is_task:
                self._validate_task_depends_on(item_id, new_depends_on)
            elif is_story:
                self._validate_story_depends_on(item_id, new_depends_on)

        for key, value in kwargs.items():
            if value is not None:
                post.metadata[key] = value
        if unassign:
            post.metadata["assignee"] = None
        post.metadata["updated"] = date.today().isoformat()

        if is_epic:
            meta = EpicFrontmatter(**post.metadata)
        elif is_task:
            meta = TaskFrontmatter(**post.metadata)
        else:
            meta = StoryFrontmatter(**post.metadata)

        path.write_text(frontmatter.dumps(post))

        # Surgically update relevant cache entry
        if is_epic:
            self._cache_update_entry("epics", item_id, meta, post.content)
        elif is_task:
            self._cache_update_entry("tasks", item_id, meta, post.content)
        else:
            self._cache_update_entry("stories", item_id, meta, post.content)

        # Reconcile auto-generated test tasks when a story's acceptance
        # criteria actually change.  Skipped entirely when the criteria are
        # untouched *and* the test tasks already agree with them, so a no-op
        # edit stays byte-for-byte a no-op.
        #
        # The "already agree" half matters: criteria edited straight in the
        # .md file never went through this method, so the drift is on disk
        # with the criteria list already at its new value.  Without the drift
        # probe, re-applying the same criteria — the obvious repair, and the
        # one pm_audit's criteria-without-test-task finding recommends —
        # would be a silent no-op and the drift would be unfixable through
        # the API.  With it, supplying a story's own criteria is a repair.
        self.last_criteria_reconciliation = None
        reconciled_paths: list[Path] = []
        if is_story:
            new_criteria = kwargs.get("acceptance_criteria")
            old_criteria = list(old_meta.get("acceptance_criteria") or [])
            needs_reconcile = new_criteria is not None and (
                list(new_criteria) != old_criteria
                or self._has_criteria_drift(item_id, list(new_criteria))
            )
            if needs_reconcile:
                (
                    self.last_criteria_reconciliation,
                    reconciled_paths,
                ) = self._reconcile_criteria_tasks(item_id, list(new_criteria))

        # Check for dependency cycles after writing the update
        if new_depends_on is not None and is_task:
            story_id = post.metadata.get("story_id", "")
            try:
                self._check_dependency_cycles(story_id)
            except ValueError:
                # Roll back: restore the original file
                post.metadata = {**old_meta, "updated": date.today().isoformat()}
                post.content = old_body
                path.write_text(frontmatter.dumps(post))
                self._invalidate_cache("tasks")
                raise

        # Build before/after field diffs for activity log
        changes: dict[str, dict] = {}
        if unassign and old_meta.get("assignee") is not None:
            changes["assignee"] = {"before": old_meta.get("assignee"), "after": None}
        for key, value in kwargs.items():
            if value is not None:
                before = old_meta.get(key)
                # Normalize enums/dates to strings for comparison
                before_str = str(before) if before is not None else None
                after_str = str(value)
                if before_str != after_str:
                    changes[key] = {"before": before, "after": value}
        if new_body is not None and new_body != old_body:
            changes["body"] = {"before": old_body, "after": new_body}

        item_type = (
            ItemType.epic if is_epic else (ItemType.task if is_task else ItemType.story)
        )
        self._emit_log(EventType.update, item_id, item_type, changes=changes)

        # Append run-log entry if outcome or note provided
        if outcome is not None or note is not None:
            self._append_run_log(
                item_id,
                outcome=outcome or Outcome.info,
                note=note or "",
                status=str(meta.status.value)
                if hasattr(meta.status, "value")
                else str(meta.status),
            )

        suffix = " ".join(commit_parts)
        msg = f"pm: update {item_id}" + (f" {suffix}" if suffix else "")
        self._auto_commit([path, *reconciled_paths], msg)

        if is_task:
            self._index_embedding(item_id, meta.title, "task", post.content)
        elif is_story:
            self._index_embedding(item_id, meta.title, "story", post.content)

        return meta

    def archive(self, item_id: str) -> None:
        """Archive an epic, story, or task.

        Epics and stories have a genuine ``archived`` status.  Tasks do not:
        archiving a task sets the orthogonal ``archived`` flag and leaves
        ``status`` alone, so abandoned work keeps the status it really reached
        instead of being recorded as completed.
        """
        if self._is_epic_id(item_id):
            self.update(item_id, status=EpicStatus.archived.value)
        elif self._is_task_id(item_id):
            self.update(item_id, archived=True)
        else:
            self.update(item_id, status=StoryStatus.archived.value)

    def unarchive(self, item_id: str) -> None:
        """Clear a task's archived flag, restoring it to its recorded status."""
        if not self._is_task_id(item_id) or self._is_epic_id(item_id):
            raise ValueError(f"unarchive only applies to tasks, got: {item_id}")
        self.update(item_id, archived=False)

    def get(
        self, item_id: str
    ) -> tuple[
        EpicFrontmatter | StoryFrontmatter | TaskFrontmatter | SprintFrontmatter, str
    ]:
        """Unified lookup by ID — dispatches to get_epic, get_story, get_task, or get_sprint."""
        if self._is_epic_id(item_id):
            return self.get_epic(item_id)
        if self._is_sprint_id(item_id):
            return self.get_sprint(item_id)
        if self._is_task_id(item_id):
            return self.get_task(item_id)
        return self.get_story(item_id)

    # ─── Changesets ───────────────────────────────────────────────

    @property
    def changesets_dir(self) -> Path:
        return self.project_dir / "changesets"

    def _next_changeset_id(self) -> str:
        cid = f"CS-{self.config.prefix}-{self.config.next_changeset_id}"
        self.config.next_changeset_id += 1
        self._save_config()
        return cid

    def _changeset_path(self, changeset_id: str) -> Path:
        return self.changesets_dir / f"{changeset_id}.md"

    def create_changeset(
        self,
        title: str,
        projects: list[str],
        description: str = "",
    ) -> ChangesetFrontmatter:
        """Create a changeset grouping changes across multiple projects."""
        self.changesets_dir.mkdir(parents=True, exist_ok=True)
        changeset_id = self._next_changeset_id()
        today = date.today()

        entries = [ChangesetEntry(project=p) for p in projects]

        meta = ChangesetFrontmatter(
            id=changeset_id,
            title=title,
            status=ChangesetStatus.open,
            entries=entries,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._changeset_path(changeset_id).write_text(frontmatter.dumps(post))
        self._emit_log(EventType.create, changeset_id, ItemType.changeset)
        return meta

    def get_changeset(self, changeset_id: str) -> tuple[ChangesetFrontmatter, str]:
        """Read a changeset, returning (frontmatter, body)."""
        path = self._changeset_path(changeset_id)
        if not path.exists():
            raise FileNotFoundError(f"Changeset not found: {changeset_id}")
        post = frontmatter.load(str(path))
        meta = ChangesetFrontmatter(**post.metadata)
        return meta, post.content

    def list_changesets(
        self, status: Optional[str] = None
    ) -> list[ChangesetFrontmatter]:
        """List all changesets, optionally filtered by status."""
        if not self.changesets_dir.exists():
            return []
        changesets = []
        for path in sorted(self.changesets_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = ChangesetFrontmatter(**post.metadata)
                if status is None or meta.status.value == status:
                    changesets.append(meta)
            except Exception:
                continue
        return changesets

    def add_changeset_entry(
        self, changeset_id: str, project: str, ref: str = ""
    ) -> ChangesetFrontmatter:
        """Add a project entry to an existing changeset."""
        meta, body = self.get_changeset(changeset_id)
        meta.entries.append(ChangesetEntry(project=project, ref=ref))
        meta.updated = date.today()

        post = frontmatter.Post(
            content=body,
            **meta.model_dump(mode="json"),
        )
        self._changeset_path(changeset_id).write_text(frontmatter.dumps(post))
        return meta

    # ─── Sprints ─────────────────────────────────────────────────

    @property
    def sprints_dir(self) -> Path:
        return self.project_dir / "sprints"

    def _next_sprint_id(self) -> str:
        sid = f"SPRINT-{self.config.prefix}-{self.config.next_sprint_id}"
        self.config.next_sprint_id += 1
        self._save_config()
        return sid

    def _sprint_path(self, sprint_id: str) -> Path:
        return self.sprints_dir / f"{sprint_id}.md"

    def _is_sprint_id(self, item_id: str) -> bool:
        return item_id.startswith("SPRINT-")

    def create_sprint(
        self,
        name: str,
        goal: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        planned_stories: Optional[list[str]] = None,
    ) -> SprintFrontmatter:
        """Create a sprint with optional planned stories."""
        self.sprints_dir.mkdir(parents=True, exist_ok=True)
        sprint_id = self._next_sprint_id()
        today = date.today()
        stories = planned_stories or []

        # Calculate planned points from stories
        planned_points = 0
        for sid in stories:
            try:
                story_meta, _ = self.get_story(sid)
                planned_points += story_meta.points or 0
            except Exception:
                pass

        meta = SprintFrontmatter(
            id=sprint_id,
            name=name,
            goal=goal,
            start_date=date.fromisoformat(start_date) if start_date else None,
            end_date=date.fromisoformat(end_date) if end_date else None,
            planned_stories=stories,
            planned_points=planned_points,
            completed_points=0,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=goal,
            **meta.model_dump(mode="json"),
        )
        self._sprint_path(sprint_id).write_text(frontmatter.dumps(post))
        self._emit_log(EventType.create, sprint_id, ItemType.sprint)
        return meta

    def get_sprint(self, sprint_id: str) -> tuple[SprintFrontmatter, str]:
        """Read a sprint, returning (frontmatter, body)."""
        path = self._sprint_path(sprint_id)
        if not path.exists():
            raise FileNotFoundError(f"Sprint not found: {sprint_id}")
        post = frontmatter.load(str(path))
        meta = SprintFrontmatter(**post.metadata)
        return meta, post.content

    def list_sprints(self, status: Optional[str] = None) -> list[SprintFrontmatter]:
        """List all sprints, optionally filtered by status."""
        if not self.sprints_dir.exists():
            return []
        sprints = []
        for path in sorted(self.sprints_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = SprintFrontmatter(**post.metadata)
                if status is None or meta.status.value == status:
                    sprints.append(meta)
            except Exception:
                continue
        return sprints

    def update_sprint(self, sprint_id: str, **kwargs) -> SprintFrontmatter:
        """Update sprint fields. Auto-computes completed_points when completing."""
        meta, body = self.get_sprint(sprint_id)
        changes = {}

        for key, value in kwargs.items():
            if value is not None and hasattr(meta, key):
                old_val = getattr(meta, key)
                if key == "status":
                    value = SprintStatus(value)
                elif key in ("start_date", "end_date") and isinstance(value, str):
                    value = date.fromisoformat(value)
                elif key == "planned_stories" and isinstance(value, str):
                    value = [s.strip() for s in value.split(",") if s.strip()]
                old_str = str(old_val) if old_val is not None else None
                new_str = str(value)
                if old_str != new_str:
                    changes[key] = {"before": old_val, "after": value}
                setattr(meta, key, value)

        # Auto-compute completed_points when status set to completed.
        #
        # This number *is* the team's velocity: future sprints are sized
        # against it.  Only genuinely delivered stories may count.  An
        # archived story was abandoned, not delivered — counting it here
        # silently raises the bar every future sprint is planned against.
        if meta.status == SprintStatus.completed:
            completed_pts = 0
            for sid in meta.planned_stories:
                try:
                    story_meta, _ = self.get_story(sid)
                    if is_archived(story_meta):
                        continue
                    if story_meta.status.value == "done":
                        completed_pts += story_meta.points or 0
                except Exception:
                    pass
            meta.completed_points = completed_pts

        # Recalculate planned_points if stories changed
        if "planned_stories" in kwargs:
            planned_pts = 0
            for sid in meta.planned_stories:
                try:
                    story_meta, _ = self.get_story(sid)
                    planned_pts += story_meta.points or 0
                except Exception:
                    pass
            meta.planned_points = planned_pts

        meta.updated = date.today()

        post = frontmatter.Post(
            content=body,
            **meta.model_dump(mode="json"),
        )
        self._sprint_path(sprint_id).write_text(frontmatter.dumps(post))
        self._emit_log(EventType.update, sprint_id, ItemType.sprint, changes=changes)
        return meta

    # ─── Git Operations ──────────────────────────────────────────

    def commit_project_changes(self, message: Optional[str] = None) -> dict:
        """Stage and commit .project/ changes with an auto-generated message.

        If *message* is provided it is used as-is; otherwise a summary is
        generated from the staged diff (e.g. "pm: add 2 stories, update 1 task").

        Returns a dict with ``commit_hash``, ``message``, and ``files_changed``.
        Raises ``RuntimeError`` if the commit fails, or :class:`NothingToCommit`
        (a ``RuntimeError`` subclass) when there was nothing to commit — the
        latter is an expected negative, not a failure.
        """
        import subprocess

        project_dir = str(self.project_dir)

        # Stage all .project/ changes
        subprocess.run(
            ["git", "add", project_dir],
            cwd=str(self.root),
            capture_output=True,
            check=True,
        )

        # Check if there are staged changes
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", project_dir],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )

        changed_files = [f for f in diff_result.stdout.strip().splitlines() if f]
        if not changed_files:
            raise NothingToCommit("No .project/ changes to commit")

        # Auto-generate message if not provided
        if message is None:
            message = self._generate_commit_message(changed_files)

        # Commit
        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )

        # Extract commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )
        commit_hash = hash_result.stdout.strip()

        return {
            "commit_hash": commit_hash,
            "message": message,
            "files_changed": changed_files,
        }

    def _generate_commit_message(self, changed_files: list[str]) -> str:
        """Generate a commit message summarizing .project/ changes."""
        stories_added = 0
        stories_updated = 0
        tasks_added = 0
        tasks_updated = 0
        epics_added = 0
        epics_updated = 0
        config_changed = False
        other = 0

        for f in changed_files:
            name = Path(f).name
            if "/stories/" in f or f.startswith("stories/"):
                # Heuristic: new files are "added", modified are "updated"
                # We can't easily distinguish from file list alone, so count all
                stories_updated += 1
            elif "/tasks/" in f or f.startswith("tasks/"):
                tasks_updated += 1
            elif "/epics/" in f or f.startswith("epics/"):
                epics_updated += 1
            elif name == "config.yaml" or name == "index.yaml":
                config_changed = True
            else:
                other += 1

        parts = []
        if stories_updated:
            parts.append(
                f"{stories_updated} {'story' if stories_updated == 1 else 'stories'}"
            )
        if tasks_updated:
            parts.append(f"{tasks_updated} {'task' if tasks_updated == 1 else 'tasks'}")
        if epics_updated:
            parts.append(f"{epics_updated} {'epic' if epics_updated == 1 else 'epics'}")
        if config_changed:
            parts.append("config")
        if other:
            parts.append(f"{other} {'file' if other == 1 else 'files'}")

        if parts:
            return f"pm: update {', '.join(parts)}"
        return "pm: update project data"

    def push_project_changes(self, remote: str = "origin") -> dict:
        """Push committed changes to the remote.

        Validates that we are on a branch (not detached HEAD) and that
        the remote exists before pushing.

        Returns a dict with ``branch`` and ``remote`` on success,
        or ``up_to_date`` if there was nothing new to push.
        Raises ``RuntimeError`` on validation or push failure.
        """
        import subprocess

        # Check we're on a branch (not detached HEAD)
        branch_result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        if branch_result.returncode != 0:
            raise RuntimeError(
                "Cannot push from a detached HEAD state — checkout a branch first"
            )

        branch = branch_result.stdout.strip()

        # Validate remote exists
        remote_result = subprocess.run(
            ["git", "remote"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )
        remotes = [
            r.strip() for r in remote_result.stdout.strip().splitlines() if r.strip()
        ]
        if remote not in remotes:
            raise RuntimeError(
                f"Remote '{remote}' not configured (available: {', '.join(remotes) or 'none'})"
            )

        # Push
        push_result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        if push_result.returncode != 0:
            stderr = push_result.stderr.strip()
            raise RuntimeError(f"Push failed: {stderr}")

        return {
            "branch": branch,
            "remote": remote,
        }
