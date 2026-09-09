"""Project audit — drift detection and consistency checks."""

import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

from .activity_log import log_paths, read_log_entries
from .deps import build_combined_dep_graph, detect_cycle
from .durations import long_task_risk
from .models import RunLogEntry
from .store import Store

# ── State digest (US-PM-11-5) ────────────────────────────────────────────
#
# pm-orchestrate polls pm_audit — once in pre-flight, then as a health check
# every 3 accepted tasks — and 92 of 139 measured calls in one session were
# byte-identical repeats.  The poll is correct (caching it would disable the
# health check); what was missing is a cheap way to say "nothing changed".
# This digest is that answer, and US-PM-11-6 compares it against a caller's
# ``since`` to short-circuit the whole report.
#
# WHAT IS HASHED, AND WHY THE WHOLE TREE: every audit check reads its inputs
# through the Store or straight off the PM directory — item files, config.yaml,
# PROJECT/INFRASTRUCTURE/SECURITY.md, malformed/, logs/*.jsonl (the
# evidence check), sprints, index files.  Enumerating those paths here would
# mean this function goes stale the day someone adds another check, so it hashes
# the *entire* PM directory instead: path + size + bytes, in sorted order.
# Over-sensitivity is safe (it costs one extra full report); under-sensitivity
# would hide a real finding, which is the failure that matters.
#
# Content, not mtime: two calls with no writes between them must agree, and a
# rewrite of identical bytes (reindex, a no-op reconcile) should not lie about
# a change.  Nothing wall-clock enters the hash.
#
# EXCLUSIONS are outputs and caches, never inputs:
#   * DRIFT.md — written by ``run_audit`` itself and now carries the digest, so
#     hashing it would make every audit change its own answer;
#   * embeddings.db and sqlite sidecars — a derived cache whose bytes move on
#     access, not on project state;
#   * __pycache__ / *.pyc and *.lock / *.tmp — scratch, not state.
#   * NEXT.md — the next-session note (US-PM-28): scratch text for a human,
#     read by no check, so rewriting it must not force a full re-audit.
#
# activity.jsonl (and its rotated siblings) is deliberately NOT excluded: as
# of US-PM-43-6 Check 17 reads it to decide which completions could have
# carried evidence, and as of US-PM-50-10 Check 18 reads it for the
# grab-to-done durations behind the long-task-risk warning, so a run-stamped
# transition written into it must move the digest or `since=` would hide the
# finding it produces.  The whole-tree walk already covers it; the rule is
# written down here so nobody adds it to the skip lists as "just a log".
# config.yaml is covered by the same walk, and Check 18 depends on it too —
# `orchestrate.max_task_minutes` is the ceiling the bands are compared with,
# so raising it must be able to clear the warning on the next audit.
DIGEST_LENGTH = 16
DIGEST_LINE_PREFIX = "digest: "

_DIGEST_SKIP_NAMES = frozenset({"DRIFT.md", "NEXT.md"})
_DIGEST_SKIP_SUFFIXES = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".lock",
    ".pyc",
    ".tmp",
)
_DIGEST_SKIP_DIRS = frozenset({"__pycache__"})


def _digest_skips(path: Path, pm_dir: Path) -> bool:
    """True for files that are audit *output* or cache, never audit input."""
    if path.name in _DIGEST_SKIP_NAMES:
        return True
    if path.name.endswith(_DIGEST_SKIP_SUFFIXES):
        return True
    return any(part in _DIGEST_SKIP_DIRS for part in path.relative_to(pm_dir).parts)


def compute_state_digest(root: Path) -> str:
    """A short, stable fingerprint of everything the audit reads.

    Returns ``DIGEST_LENGTH`` lowercase hex characters — fixed width, cheap to
    log, cheap to compare.  Equal digests mean no audit input changed; a
    different digest means something did.

    *root* resolves exactly as ``Store`` resolves it, so the digest always
    covers the same directory the audit reads: ``root/.project``.

    Callers may compute this without running the audit — that is how
    US-PM-11-6 answers an unchanged project in a few bytes.  Measured on this
    repo's own ``.project`` (791 files, 1.3 MB of hashed bytes): 106 ms against
    5,056 ms for a full ``run_audit`` — about 2% of the work it can skip.
    """
    pm_dir = root / ".project"
    hasher = hashlib.sha256()
    # Version tag: bump if the hashing rule changes, so stale digests from an
    # older build compare unequal instead of falsely matching.
    hasher.update(b"projectman-audit-state-v1\0")

    if pm_dir.is_dir():
        for path in sorted(p for p in pm_dir.rglob("*") if p.is_file()):
            if _digest_skips(path, pm_dir):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                # Vanished or unreadable mid-walk; skip rather than hash a
                # sentinel that would flap between calls.
                continue
            hasher.update(path.relative_to(pm_dir).as_posix().encode())
            hasher.update(b"\0")
            hasher.update(str(len(data)).encode())
            hasher.update(b"\0")
            hasher.update(data)

    return hasher.hexdigest()[:DIGEST_LENGTH]


UNCHANGED_LINE = "unchanged: true"

_COUNTS_RE = re.compile(
    r"\*\*Errors:\*\* (\d+) \| \*\*Warnings:\*\* (\d+) \| \*\*Info:\*\* (\d+)"
)


def _last_report_counts(pm_dir: Path, digest: str) -> Optional[tuple[int, int]]:
    """(errors, warnings) from DRIFT.md — only if it describes *this* state.

    DRIFT.md carries the digest of the state it was rendered from, so a
    matching digest line is proof the counts below it are still current.  Any
    other outcome (no file, older digest, unparseable header) returns None and
    the caller simply omits the counts; it never re-runs the checks to get
    them, and it never reports counts it cannot vouch for.
    """
    try:
        text = (pm_dir / "DRIFT.md").read_text()
    except OSError:
        return None
    if f"{DIGEST_LINE_PREFIX}{digest}" not in text.splitlines():
        return None
    match = _COUNTS_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def unchanged_report(root: Path, digest: str) -> str:
    """The few-byte answer for "nothing changed since *digest*" (US-PM-11-6).

    Under 100 bytes against the 162-10,440 char full report, and it performs no
    check and no DRIFT.md write — the digest already proved there is nothing
    new to say.
    """
    pm_dir = root / ".project"
    lines = [f"{DIGEST_LINE_PREFIX}{digest}", UNCHANGED_LINE]
    counts = _last_report_counts(pm_dir, digest)
    if counts is not None:
        lines.append(f"errors: {counts[0]} | warnings: {counts[1]}")
    return "\n".join(lines) + "\n"


# ── Check 17's rule: which completions could have carried evidence ───────
#
# The evidence contract (US-PM-9, Sprint 4) shipped long after this project
# started completing tasks, so "done with no evidence" once meant 447 tasks on
# this repo alone — a count that can never shrink, because the only way to
# move it is to rewrite history.  A warning nobody can act on is noise, and
# noise is what hides the warning that matters (US-PM-43).
#
# The cutoff is what the record shows, not a date, so it needs no maintenance
# as history rolls forward.  A done task is counted only when the completion
# *could* have carried evidence:
#
#   1. its run log has an entry written no earlier than the first
#      evidence-bearing run-log entry anywhere in this store — by then the
#      contract was demonstrably in use here, so whoever wrote that verdict
#      could have attached evidence to it; or
#   2. its transition to ``done`` was made under an orchestrator run — an
#      activity-log ``update`` event whose ``changes.status.after`` is
#      ``"done"`` and whose ``run_id`` is set.
#
# A done task with neither is a pre-contract completion: nothing was ever
# written that evidence could have hung off, and nobody can go back and add
# one.  It is not counted.
#
# WHY THE STORE'S OWN FIRST EVIDENCE IS THE LINE, and not a date: the contract
# shipped on different days for different projects, and a project that adopts
# ProjectMan tomorrow imports history that predates it entirely.  The store
# proves its own adoption — the earliest entry it holds that carries evidence
# is the first moment anyone here demonstrably could have written some.  The
# 67 remaining warnings on this repo were all verdicts (note/outcome) written
# before that moment; none can gain evidence now without editing history.
#
# A store whose logs contain no evidence at all has never used the contract,
# so limb 1 counts nothing there — but limb 2 is unconditional, so the very
# first orchestrator run that accepts a task without evidence is caught even
# in a project that has never recorded any.


def _run_stamped_done_ids(store: Store) -> set[str]:
    """Item ids whose transition to ``done`` was made under a run (US-PM-43-6).

    One pass over the activity log per audit — not one per done task.  The log
    on this repo is ~1,400 lines and the check runs over hundreds of done
    tasks, so this reads it exactly once and the caller does set membership
    against the result.

    Raw log dicts, as ``read_log_entries`` yields them: lines written by older
    builds may lack ``run_id`` altogether, so every field is probed by name and
    type-checked rather than validated into a model.  One odd historical line
    must never make the audit refuse to answer.
    """
    stamped: set[str] = set()
    for entry in read_log_entries(log_paths(store.project_dir)):
        if entry.get("event_type") != "update" or not entry.get("run_id"):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, dict):
            continue
        status = changes.get("status")
        if isinstance(status, dict) and status.get("after") == "done":
            item_id = entry.get("item_id")
            if item_id:
                stamped.add(item_id)
    return stamped


def _as_utc(moment: datetime) -> datetime:
    """A naive timestamp is UTC — old log lines were written without an offset.

    Comparing a naive datetime with an aware one raises, and one hand-edited
    line must never make the audit refuse to answer.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _first_evidence_timestamp(store: Store) -> Optional[datetime]:
    """When this store first recorded structured evidence, or ``None``.

    One pass over ``.project/logs/*.jsonl`` per audit, cheap in the common
    case: a file whose bytes never contain ``"evidence"`` is skipped without
    parsing a line, and within a file only the lines carrying that key are
    validated.  ``None`` means the contract has never been used here, which
    Check 17 reads as "no run-log entry in this store could have carried
    evidence" (see the rule above).
    """
    logs_dir = store.project_dir / "logs"
    if not logs_dir.is_dir():
        return None
    earliest: Optional[datetime] = None
    for path in sorted(logs_dir.glob("*.jsonl")):
        try:
            text = path.read_text()
        except OSError:  # pragma: no cover - unreadable log, not a finding
            continue
        if '"evidence"' not in text:
            continue
        for line in text.splitlines():
            if '"evidence"' not in line:
                continue
            try:
                entry = RunLogEntry.model_validate_json(line)
            except Exception:
                continue
            if entry.evidence is None:
                continue
            moment = _as_utc(entry.timestamp)
            if earliest is None or moment < earliest:
                earliest = moment
    return earliest


def check_completions_without_evidence(
    store: Store, done_tasks: Optional[list] = None
) -> list[dict]:
    """Find ``done`` tasks that could have carried evidence and did not.

    THE RULE (US-PM-9-8, narrowed by US-PM-43-6 and US-PM-43-7).  A completion
    without evidence is a task with ``status == done`` whose run log contains
    no entry whose ``evidence`` is not ``None`` **and** whose completion could
    have carried evidence in the first place, meaning either

      * its run log has an entry written no earlier than this store's first
        evidence-bearing entry — by then the contract was in use here, so that
        verdict could have carried evidence and carried none; or
      * its ``done`` transition carries a ``run_id`` — an orchestrator
        accepted it, under a contract that asks for evidence.

    Everything else is a pre-contract completion and is **not** counted: a
    done task with no run log and no run-stamped completion has no entry to
    attach evidence to and no run to have attached it, and a verdict written
    before this store had ever recorded evidence could not have carried any.
    The only way to clear such a warning would be to rewrite history.  That
    was 447 tasks on this repo, then 67 — numbers that could never shrink,
    drowning the findings a reader can act on (US-PM-43).

    The line is what the store proves about itself, never a magic date: the
    contract shipped on different days for different projects, and an imported
    history predates it entirely.  A store with no evidence anywhere has never
    used the contract, so the first limb counts nothing there — while the
    second limb is unconditional, so the first orchestrator run that accepts
    without evidence is caught even in a project that has recorded none.

    Presence, never truthiness: ``Evidence()`` with four empty lists explicitly
    says "nothing to show" — the genuinely non-code task (docs, a config
    decision) that pm-orchestrate step 17 already carves out of the empty-diff
    rule.  *Absent* evidence is the gap, so this tests ``evidence is not None``
    and never the truthiness of the lists.  ``Store.get_run_log`` applies the
    ``has_evidence`` filter before ``limit``, so asking for one evidence-bearing
    entry is an existence probe: one pass over the log per done task, and no
    re-parse of anything the other checks already read.  The second probe —
    the newest entry without evidence, which ``limit=1`` returns because the
    log reads most-recent-first — is only made for tasks that failed the
    first, so a project whose completions are evidenced pays nothing for it.
    The logs directory and the activity log are each read at most once per
    call, and only on demand (see ``_first_evidence_timestamp`` and
    ``_run_stamped_done_ids``).

    Archived tasks are skipped — an archived task is abandoned history, not a
    completion anyone is still standing behind.

    One aggregate finding, the shape of ``done-story-incomplete-tasks``, so
    DRIFT.md gets one line rather than one per task.

    SEVERITY: warning, not error, for the reason written at Check 16 below.
    /pm-orchestrate halts a sprint on any error-level finding, so error is
    reserved for structural contradictions — a done story with open tasks, a
    dependency cycle.  This is a coverage gap: nothing is lost and nothing is
    unreachable.  The narrowed rule makes the count actionable but not
    necessarily small — a project that completed tasks through verdicts before
    evidence existed still has entries with nothing attached — so it stays a
    warning.

    *done_tasks* is the already-filtered list of live done tasks — what
    ``list_tasks(status="done", archived=False)`` would return — so
    ``run_audit`` can hand over the snapshot it loaded once (US-PRJ-42)
    instead of making this the sixteenth list call.  ``None`` loads it here,
    which is what a standalone caller wants.
    """
    if done_tasks is None:
        done_tasks = store.list_tasks(status="done", archived=False)

    run_stamped: Optional[set[str]] = None
    first_evidence: Optional[datetime] = None
    first_evidence_read = False
    offenders = []
    for task in done_tasks:
        # limit=1: existence probe, not a fetch — see docstring.
        if store.get_run_log(task.id, limit=1, has_evidence=True):
            continue
        latest = store.get_run_log(task.id, limit=1)
        if latest:
            if not first_evidence_read:
                # Read once, and only if some done task has a bare verdict.
                first_evidence = _first_evidence_timestamp(store)
                first_evidence_read = True
            if (
                first_evidence is not None
                and _as_utc(latest[0].timestamp) >= first_evidence
            ):
                # A verdict written under the contract, with nothing attached.
                offenders.append(task.id)
                continue
        if run_stamped is None:
            # Read once, and only if some done task got this far.
            run_stamped = _run_stamped_done_ids(store)
        if task.id in run_stamped:
            offenders.append(task.id)

    if not offenders:
        return []
    return [{
        "severity": "warning",
        "check": "done-without-evidence",
        "message": (
            f"{len(offenders)} done task(s) that could have carried evidence "
            f"have none on any run-log entry — record files/tests/dod_met with "
            f"the verdict (counted only where a run-log entry was written at "
            f"or after this project's first evidence, or the done transition "
            f"carried a run_id)"
        ),
        "items": offenders,
    }]


# ── Documentation checks (US-PRJ-42-6) ───────────────────────────────────
#
# The project docs (PROJECT/INFRASTRUCTURE/SECURITY.md) test "is this still
# the template?" with one line filter and one piece of mtime arithmetic: the
# filter is ``_content_lines`` and the whole check lives in
# ``_check_documentation``.
#
# The ``*Last reviewed: …*`` / ``*Update this …*`` lines are dropped along with
# the headings and table rules because every one of those templates ends in
# that footer, so leaving them in would make an untouched template read as
# filled.
_DOC_SKIP_PREFIXES = (
    "#", "<!--", "-->", "---", "|", "*Last reviewed", "*Update this",
)

# A doc with fewer real content lines than this is treated as an unfilled
# template (a heading-and-boilerplate skeleton).
_UNFILLED_DOC_MAX_LINES = 3

# Days since last modification before a doc is reported as stale.
_STALE_DOC_DAYS = 30


def _content_lines(
    text: str,
    skip_prefixes: tuple[str, ...] = _DOC_SKIP_PREFIXES,
) -> list[str]:
    """Real content lines of a doc — headings, comments and boilerplate dropped.

    Used to tell a filled-in doc from an untouched template: what is left after
    stripping headings, HTML comment delimiters, rules, table rows and the
    template footer is the prose someone actually wrote.
    """
    stripped = (line.strip() for line in text.splitlines())
    return [
        line for line in stripped
        if line and not line.startswith(skip_prefixes)
    ]


def _check_documentation(
    project_dir: Path,
    doc_files: dict[str, list[str]],
    today: date,
) -> list[dict]:
    """Missing / unfilled / stale checks over the project's six-doc context.

    *doc_files* maps a doc filename to its required sections (kept for the
    caller's own documentation of what each doc should contain; section
    presence is not asserted here).  *today* anchors the staleness arithmetic
    so callers and tests share one clock.
    """
    findings: list[dict] = []
    for doc_name in doc_files:
        doc_path = project_dir / doc_name
        if not doc_path.exists():
            findings.append({
                "severity": "error",
                "check": "missing-documentation",
                "message": f"{doc_name} is missing from .project/",
                "items": [doc_name],
            })
            continue

        if len(_content_lines(doc_path.read_text())) < _UNFILLED_DOC_MAX_LINES:
            findings.append({
                "severity": "warning",
                "check": "unfilled-documentation",
                "message": f"{doc_name} appears to be an unfilled template — needs real content",
                "items": [doc_name],
            })

        mtime = date.fromtimestamp(os.path.getmtime(doc_path))
        age_days = (today - mtime).days
        if age_days > _STALE_DOC_DAYS:
            findings.append({
                "severity": "info",
                "check": "stale-documentation",
                "message": f"{doc_name} hasn't been updated in {age_days} days",
                "items": [doc_name],
            })
    return findings


# ── Check 18's rule: long-task risk in the sprint that is running ─────────
#
# US-PM-50 measured this project's own grab-to-done durations and found the
# tail, not the median, is what breaks an orchestrator run: every prompt-cache
# miss in a long run sat right after a worker wait over the one-hour TTL.
# ``durations.long_task_risk`` is the shared judgement — a task is flagged when
# its points band has a p90 above ``orchestrate.max_task_minutes`` and the band
# has enough samples to be a percentile at all — and pm_get_sprint already
# reports it to a planner.  The audit is the second surface: a sprint that was
# activated without splitting those tasks should say so, once per task, every
# time anyone looks.
#
# SEVERITY: warning, never error, for the same reason as Checks 16 and 17 —
# /pm-orchestrate halts on any error-level finding, and "the tasks you are
# about to run are large" must not be the thing that stops the run that would
# have worked through them.  It is advice for the next planning pass.
#
# Only sprints whose status is ``active`` are considered.  A planning sprint is
# still being shaped (that is pm-plan's check, US-PM-50-11, before it
# activates), and a completed one cannot be re-scoped.
def check_long_task_risk(store: Store) -> list[dict]:
    """Warn for each open task of an active sprint whose band runs long.

    One finding per flagged task, carrying the band numbers the reader needs
    to judge it — the median and p90 of that points band, and the ceiling they
    are measured against — so the message stands on its own without a second
    call to pm_get_sprint.

    A project with no active sprint, no duration history, or no band over the
    ceiling produces nothing; this check never raises on log content, because
    everything it reads goes through :mod:`projectman.durations`, which treats
    the activity log as history no reader may repair.
    """
    findings: list[dict] = []
    for sprint in store.list_sprints(status="active"):
        for entry in long_task_risk(store, sprint):
            findings.append({
                "severity": "warning",
                "check": "long-task-risk",
                "message": (
                    f"Task {entry['id']} ({entry['points']}pt) in active sprint "
                    f"{sprint.id} is in a band that runs "
                    f"{entry['p50']:g} min median, {entry['p90']:g} min p90 — over the "
                    f"{entry['max_task_minutes']:g} min max_task_minutes ceiling; "
                    "split it or expect a prompt-cache miss"
                ),
                "items": [entry["id"]],
            })
    return findings


def run_audit(
    root: Path,
    include_info: bool = True,
    since: Optional[str] = None,
) -> str:
    """Run all audit checks and generate a report. Also writes DRIFT.md.

    The Store is rooted at *root* and reads PM data from ``root/.project/``.

    When *include_info* is False, info-level findings are omitted from the
    returned report (summarized as a count); DRIFT.md always gets the full report.

    Every rendering — the normal response, the include_info response, and
    DRIFT.md — carries a ``digest: <16 hex>`` line as the first line after the
    title (US-PM-11-5).  It fingerprints the audit's inputs, so an orchestrator
    can tell an unchanged project from a changed one without diffing reports.

    When *since* equals that digest, this returns ``unchanged_report`` instead
    — a sub-100-byte answer, with no check run and no DRIFT.md write
    (US-PM-11-6).  **This does not weaken the health check.** The digest is a
    content hash of the audit's entire input tree, so any state change that
    could produce a new finding necessarily changes the digest; a matching
    digest therefore implies byte-identical inputs, which implies identical
    findings — a new ERROR is impossible to hide behind it.  The hash is
    deliberately over-sensitive (an unrelated write costs one extra full
    report) because under-sensitivity is the failure that matters.  A *since*
    that is stale, malformed, or from an older hashing rule simply fails to
    match and the full audit runs; it is never an error.
    """
    # Computed up front, off the same directory the checks below read
    # (US-PM-11-5).  DRIFT.md is excluded from the hash, so writing the report
    # at the end of this function cannot perturb the digest it reports — and
    # it is the only work done before the short-circuit decision, measured at
    # ~2% of a full audit on this repo's own .project.
    digest = compute_state_digest(root)
    if since is not None and since.strip().lower() == digest:
        return unchanged_report(root, digest)

    store = Store(root)
    findings = []

    # ── The snapshot every check below reads (US-PRJ-42) ──────────────────
    #
    # One read per collection, up front, and every check works off these
    # lists.  The checks used to each go back to the Store — three separate
    # ``list_stories()`` calls, a ``list_tasks(story_id=...)`` per story, a
    # ``get_story``/``get_task`` per item — which is an N+1 whose cost grows
    # with the backlog even though every one of those calls returns the same
    # data within a single audit.
    #
    # The filtered views below are built to be *exactly* what the Store's own
    # filters return, so the findings and their order are unchanged:
    #   * ``list_stories()`` / ``list_epics()`` exclude archived items (they
    #     are not in the cache at all), so the snapshots do too;
    #   * ``list_tasks()`` includes archived tasks — the checks that must not
    #     see them filter explicitly, as they always did;
    #   * every view preserves the source list's order, which is the
    #     filename sort the Store hands back, so DRIFT.md does not churn.
    #
    # Bodies come from the ``*_with_bodies`` reads rather than a ``get_*``
    # per item: ``get_story``/``get_task`` are linear scans of the cache, so
    # the old per-item loop was quadratic on top of being repetitive.
    story_entries = store.list_stories_with_bodies()
    task_entries = store.list_tasks_with_bodies()
    all_stories = [meta for meta, _ in story_entries]
    all_tasks = [meta for meta, _ in task_entries]
    all_epics = store.list_epics()
    story_bodies = {meta.id: body for meta, body in story_entries}
    task_bodies = {meta.id: body for meta, body in task_entries}

    tasks_by_story: dict[str, list] = {}
    for task in all_tasks:
        # ``list_tasks(story_id=...)`` matches on a truthy story_id, so a task
        # with none belonged to no story there either.
        if task.story_id:
            tasks_by_story.setdefault(task.story_id, []).append(task)
    stories_by_epic: dict[str, list] = {}
    for story in all_stories:
        if story.epic_id:
            stories_by_epic.setdefault(story.epic_id, []).append(story)

    stories_done = [s for s in all_stories if s.status.value == "done"]
    tasks_in_progress = [t for t in all_tasks if t.status.value == "in-progress"]
    tasks_done_live = [
        t for t in all_tasks if t.status.value == "done" and t.archived is False
    ]
    epics_active = [e for e in all_epics if e.status.value == "active"]
    epics_done = [e for e in all_epics if e.status.value == "done"]
    epics_draft = [e for e in all_epics if e.status.value == "draft"]

    # Check 1: Done stories with incomplete tasks
    for story in stories_done:
        tasks = tasks_by_story.get(story.id, [])
        # An archived task is abandoned, not outstanding — it must not be
        # reported as work the done story still owes.  Archival used to write
        # "done", which excluded it here as a side effect (US-PM-16).
        incomplete = [t for t in tasks if t.status.value != "done" and not t.archived]
        if incomplete:
            findings.append({
                "severity": "error",
                "check": "done-story-incomplete-tasks",
                "message": f"Story {story.id} is done but has {len(incomplete)} incomplete task(s)",
                "items": [t.id for t in incomplete],
            })

    # Check 2: Undecomposed stories (active/ready stories with no tasks)
    for story in all_stories:
        if story.status.value in ("active", "ready"):
            tasks = tasks_by_story.get(story.id, [])
            if not tasks:
                findings.append({
                    "severity": "warning",
                    "check": "undecomposed-story",
                    "message": f"Story {story.id} is {story.status.value} but has no tasks",
                    "items": [story.id],
                })

    # Check 3: Stale in-progress items (>14 days)
    stale_threshold = date.today() - timedelta(days=14)
    for task in tasks_in_progress:
        if task.updated < stale_threshold:
            days = (date.today() - task.updated).days
            findings.append({
                "severity": "warning",
                "check": "stale-in-progress",
                "message": f"Task {task.id} has been in-progress for {days} days",
                "items": [task.id],
            })

    # Check 4: Point mismatches (story points != sum of task points)
    for story in all_stories:
        if story.points:
            tasks = tasks_by_story.get(story.id, [])
            task_points = sum(t.points or 0 for t in tasks)
            if tasks and task_points > 0 and task_points != story.points:
                findings.append({
                    "severity": "info",
                    "check": "point-mismatch",
                    "message": f"Story {story.id} has {story.points}pts but tasks sum to {task_points}pts",
                    "items": [story.id],
                })

    # Check 5: Thin descriptions (body < 20 chars)
    for story in all_stories:
        body = story_bodies[story.id]
        if len(body.strip()) < 20:
            findings.append({
                "severity": "info",
                "check": "thin-description",
                "message": f"Story {story.id} has a thin description ({len(body.strip())} chars)",
                "items": [story.id],
            })

    for task in all_tasks:
        body = task_bodies[task.id]
        if len(body.strip()) < 20:
            findings.append({
                "severity": "info",
                "check": "thin-description",
                "message": f"Task {task.id} has a thin description ({len(body.strip())} chars)",
                "items": [task.id],
            })

    # Check 6: Active/ready stories missing acceptance criteria
    for story in all_stories:
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
    findings.extend(_check_documentation(store.project_dir, doc_files, date.today()))

    # Check 7: Empty active epic (active epic with no linked stories)
    for epic in epics_active:
        linked = stories_by_epic.get(epic.id, [])
        if not linked:
            findings.append({
                "severity": "warning",
                "check": "empty-active-epic",
                "message": f"Epic {epic.id} is active but has no linked stories",
                "items": [epic.id],
            })

    # Check 8: Done epic with open stories
    for epic in epics_done:
        linked = stories_by_epic.get(epic.id, [])
        open_stories = [s for s in linked if s.status.value not in ("done", "archived")]
        if open_stories:
            findings.append({
                "severity": "error",
                "check": "done-epic-open-stories",
                "message": f"Epic {epic.id} is done but has {len(open_stories)} open story/stories",
                "items": [s.id for s in open_stories],
            })

    # Check 9: Orphaned epic reference (story references non-existent epic_id)
    epic_ids = {e.id for e in all_epics}
    for story in all_stories:
        if story.epic_id and story.epic_id not in epic_ids:
            findings.append({
                "severity": "warning",
                "check": "orphaned-epic-reference",
                "message": f"Story {story.id} references non-existent epic {story.epic_id}",
                "items": [story.id],
            })

    # Check 10: Stale draft epic (draft >30 days with no stories)
    draft_threshold = date.today() - timedelta(days=30)
    for epic in epics_draft:
        if epic.updated < draft_threshold:
            linked = stories_by_epic.get(epic.id, [])
            if not linked:
                days = (date.today() - epic.updated).days
                findings.append({
                    "severity": "info",
                    "check": "stale-draft-epic",
                    "message": f"Epic {epic.id} has been in draft for {days} days with no stories",
                    "items": [epic.id],
                })

    # Check 11: Stale task assignment (in-progress with assignee, no updates in 14+ days)
    for task in tasks_in_progress:
        if task.assignee and task.updated < stale_threshold:
            days = (date.today() - task.updated).days
            findings.append({
                "severity": "warning",
                "check": "stale-assignment",
                "message": f"Task {task.id} assigned to {task.assignee} with no updates for {days} days",
                "items": [task.id],
            })

    # Check 12: Malformed files in quarantine
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

    # Check 13: Dependency cycles (project-wide, across tasks and stories)
    # Both lists are the snapshot loaded at the top — this check used to
    # re-read them from the Store.
    if all_tasks or all_stories:
        graph = build_combined_dep_graph(all_tasks, all_stories)
        cycle = detect_cycle(graph)
        if cycle is not None:
            path = " -> ".join(cycle)
            findings.append({
                "severity": "error",
                "check": "dependency-cycle",
                "message": f"Dependency cycle detected: {path}",
                "items": cycle,
            })

    # Check 14: Orphaned dependency references (project-wide)
    all_task_ids = {t.id for t in all_tasks}
    all_story_ids = {s.id for s in all_stories}
    all_known_ids = all_task_ids | all_story_ids

    # Check task dependencies
    for task in all_tasks:
        orphans = [dep for dep in task.depends_on if dep not in all_known_ids]
        for orphan in orphans:
            findings.append({
                "severity": "warning",
                "check": "orphaned-dependency",
                "message": f"Task {task.id} depends on {orphan} which does not exist",
                "items": [task.id, orphan],
            })

    # Check story dependencies
    for story in all_stories:
        orphans = [dep for dep in story.depends_on if dep not in all_known_ids]
        for orphan in orphans:
            findings.append({
                "severity": "warning",
                "check": "orphaned-dependency",
                "message": f"Story {story.id} depends on {orphan} which does not exist",
                "items": [story.id, orphan],
            })

    # Check 15: Missing implementation tasks (only test tasks, no impl tasks)
    for story in all_stories:
        if story.status.value in ("active", "ready"):
            tasks = tasks_by_story.get(story.id, [])
            if tasks and all(t.title.startswith("Test: ") for t in tasks):
                findings.append({
                    "severity": "warning",
                    "check": "missing-implementation-tasks",
                    "message": f"Story {story.id} has {len(tasks)} test task(s) but no implementation tasks — needs scoping before sprint",
                    "items": [story.id],
                })

    # Check 16: Acceptance-criteria / test-task drift (US-PM-5-7)
    #
    # Editing a story's acceptance criteria used to leave its auto-generated
    # test tasks quoting the old text and create nothing for the new — and the
    # audit said "Project is clean" the whole time.  Two findings, both
    # sourced from Store.detect_criteria_drift so the audit and the reconciler
    # can never disagree about what counts as a match.
    #
    # SEVERITY: warning, not error, and that is a deliberate choice.
    # /pm-orchestrate halts a sprint on any error-level finding, so error is
    # reserved here for structural contradictions — a done story with open
    # tasks, a dependency cycle, missing documentation.  This is a coverage
    # gap, not corruption: nothing is lost, nothing is unreachable, and one
    # pm_update with the story's own criteria repairs it.  The matching is
    # also a similarity heuristic, and a project whose test tasks were
    # written by hand or imported would trip it on every story; at error
    # level that false positive would brick the orchestrator for the whole
    # project, while at warning level it costs a line in DRIFT.md.  It sits
    # with its siblings missing-acceptance-criteria and
    # missing-implementation-tasks, which are warnings for the same reason.
    #
    # Stories with no acceptance criteria are NOT skipped, deliberately.  They
    # were until US-PM-5-10, and that hid the one case the flag exists for:
    # remove every criterion from a story and its worked-on test tasks are
    # flagged rather than archived, but the flag was then only ever visible in
    # the pm_update response that raised it.  detect_criteria_drift reports no
    # "missing" for a story with no criteria, so a criteria-less story that
    # has no stale test tasks still costs nothing here.
    #
    # The story's own criteria and the pre-loaded task bodies are handed in,
    # so the detector reuses this audit's snapshot instead of doing its own
    # get_story plus two list_tasks per story (US-PRJ-42).  It is still the
    # same detector — the audit and the reconciler cannot disagree — it just
    # no longer re-reads what is already in hand.
    #
    # Archived stories are skipped entirely: nothing about them is live.
    # Done stories are skipped for criteria-without-test-task only (US-PM-43-5).
    # That finding's whole remedy is "re-apply the criteria with pm_update to
    # reconcile", and on a done story that would create todo test tasks under
    # work that is already finished — its criteria were verified some other
    # way, so there is nothing left to act on and the warning can never be
    # cleared honestly.  US-PM-1 and US-PM-2 sat in exactly that state for
    # weeks.  Backlog, ready and active stories still fire: for them the
    # remedy is real.  The stale-criterion finding is deliberately NOT
    # skipped for done stories — a test task quoting text that no longer
    # exists is a wrong artifact on disk whatever the story's status, and it
    # is fixed by reconciling or archiving the task, not by adding work.
    for story in all_stories:
        if story.status.value == "archived":
            continue
        drift = store.detect_criteria_drift(
            story.id,
            criteria=list(story.acceptance_criteria or []),
            task_entries=task_entries,
        )
        if drift["missing"] and story.status.value != "done":
            findings.append({
                "severity": "warning",
                "check": "criteria-without-test-task",
                "message": (
                    f"Story {story.id} has {len(drift['missing'])} acceptance "
                    f"criterion/criteria with no test task — re-apply the criteria "
                    f"with pm_update to reconcile"
                ),
                "items": [story.id],
            })
        if drift["stale"]:
            findings.append({
                "severity": "warning",
                "check": "test-task-stale-criterion",
                "message": (
                    f"Story {story.id} has {len(drift['stale'])} test task(s) quoting "
                    f"an acceptance criterion that no longer exists"
                ),
                "items": [e["task_id"] for e in drift["stale"]],
            })

    # Check 17: Completions carrying no evidence (US-PM-9-8).  Warning, not
    # error, for the same reason as Check 16 — see the docstring on
    # check_completions_without_evidence.
    findings.extend(check_completions_without_evidence(store, tasks_done_live))

    # Check 18: Tasks in the active sprint whose size band usually overruns
    # the orchestrator's prompt cache (US-PM-50-10).
    findings.extend(check_long_task_risk(store))

    # Generate report
    error_count = sum(1 for f in findings if f["severity"] == "error")
    warn_count = sum(1 for f in findings if f["severity"] == "warning")
    info_count = sum(1 for f in findings if f["severity"] == "info")
    header = f"**Errors:** {error_count} | **Warnings:** {warn_count} | **Info:** {info_count}\n"

    def _render(items: list[dict], footer: Optional[str] = None) -> str:
        lines = [
            "# Project Audit Report\n",
            f"{DIGEST_LINE_PREFIX}{digest}\n",
            header,
        ]
        if not findings:
            lines.append("No issues found. Project is clean.\n")
        else:
            for f in items:
                icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}[f["severity"]]
                lines.append(f"- {icon} {f['message']}")
            if footer:
                lines.append(footer)
        return "\n".join(lines)

    # Write DRIFT.md (always the full report)
    report = _render(findings)
    drift_path = store.project_dir / "DRIFT.md"
    drift_path.write_text(report + "\n")

    if include_info or not info_count:
        return report
    visible = [f for f in findings if f["severity"] != "info"]
    return _render(
        visible,
        footer=f"\n({info_count} info finding(s) omitted — see DRIFT.md or pass include_info=true)",
    )
