"""Claim ownership and staleness metadata (US-PM-14-5).

US-PM-7 made claiming atomic, so two workers can never both hold a task.  It
did not make a claim *recoverable*: a run that died mid-loop left tasks sitting
at `in-progress` assigned to "claude", and the only fact on disk — the
assignee — is true of every task any agent ever touched.  Nothing distinguished
a task being worked right now from one abandoned forty minutes ago, so
pm-orchestrate's Phase 1 guessed and then asked a human.

This module pins the two fields that end the guess:

* `claimed_by_run` — *which run* took the task, so a restarting orchestrator can
  ask "is this mine?" instead of "is this claude's?" (it always is).
* `claimed_at` — *when*, so "abandoned" is a threshold rather than an inference.

and the three rules that keep them honest:

1. Every claim records both — a caller that never passes a `run_id` still gets
   the server's per-process id, so there is no such thing as an unowned claim.
2. Release and completion clear both.  They describe a claim *in force*; left
   behind, they would age every finished task into a phantom stale claim.
3. A task file written before these fields existed loads, and is *unknown-age*,
   never stale.  Treating a missing timestamp as "old" would have a recovery
   loop steal live work from an older writer on its first run.

Staleness is surfaced on `pm_active` / `pm_board` rather than through a new
tool: the question is asked at exactly the moment a caller is already listing
in-progress work.  Age is asserted by backdating `claimed_at` on disk rather
than by mocking the clock, so the real read path — YAML round-trip, timezone
normalisation, threshold compare — is what is under test.
"""

from datetime import datetime, timedelta, timezone

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.store import (
    PROCESS_RUN_ID,
    Store,
    claim_age_seconds,
    is_stale_claim,
)

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _story_with_tasks(store: Store, n_tasks: int = 1) -> Store:
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, n_tasks + 1):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    return store


def _backdate_claim(store: Store, task_id: str, minutes: int) -> datetime:
    """Rewrite `claimed_at` on disk to `minutes` ago and return the new value.

    Editing the file rather than the clock keeps the YAML round-trip in the
    test: `claimed_at` is written as an ISO string and read back through
    pydantic, and that path is where a timezone bug would live.
    """
    import frontmatter

    from projectman.store import clear_all_caches

    path = store.tasks_dir / f"{task_id}.md"
    post = frontmatter.load(str(path))
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    post.metadata["claimed_at"] = when.isoformat()
    path.write_text(frontmatter.dumps(post))
    clear_all_caches()
    return when


def _write_config_value(tmp_project, hours) -> None:
    """Set `stale_claim_hours` in config.yaml, after the fixture's own writes.

    `create_story` rewrites config.yaml to bump `next_story_id`, so a key set
    before the story exists would be overwritten by the fixture rather than
    read by the code under test.
    """
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    path = tmp_project / ".project" / "config.yaml"
    data = yaml.safe_load(path.read_text())
    data["stale_claim_hours"] = hours
    path.write_text(yaml.safe_dump(data))
    clear_all_caches()
    _store_cache.clear()


def _activity(tmp_project) -> list[dict]:
    import json

    log = tmp_project / ".project" / "activity.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


# ═══ 1. A claim records who and when ════════════════════════════


def test_claim_records_the_run_id_it_was_given(store):
    _story_with_tasks(store)
    won, meta = store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    assert won is True
    assert meta.claimed_by_run == "run-alpha"


def test_claim_records_a_timestamp(store):
    _story_with_tasks(store)
    before = datetime.now(timezone.utc)
    _, meta = store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    after = datetime.now(timezone.utc)
    assert meta.claimed_at is not None
    assert before <= meta.claimed_at <= after


def test_claim_metadata_is_durable_not_just_returned(store):
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    on_disk, _ = Store(store.root).get_task("US-TST-1-1")
    assert on_disk.claimed_by_run == "run-alpha"
    assert on_disk.claimed_at is not None


def test_a_claim_without_a_run_id_still_has_an_owner(store):
    """There is no such thing as an unowned claim — that is the whole point."""
    _story_with_tasks(store)
    _, meta = store.claim_task("US-TST-1-1", "claude")
    assert meta.claimed_by_run == PROCESS_RUN_ID
    assert meta.claimed_at is not None


def test_claimed_at_is_timezone_aware_utc(store):
    _story_with_tasks(store)
    _, meta = store.claim_task("US-TST-1-1", "claude")
    reread, _ = Store(store.root).get_task("US-TST-1-1")
    assert reread.claimed_at.tzinfo is not None
    assert reread.claimed_at.utcoffset() == timedelta(0)


def test_assignee_semantics_are_unchanged(store):
    """The new fields sit beside `assignee`; they do not replace it."""
    _story_with_tasks(store)
    _, meta = store.claim_task("US-TST-1-1", "worker-1", run_id="run-alpha")
    assert meta.assignee == "worker-1"
    assert meta.status.value == "in-progress"


# ═══ 2. Re-claim is idempotent; a takeover is not ═══════════════


def test_reclaim_by_the_same_run_keeps_the_original_timestamp(store):
    """Otherwise a wedged loop re-grabbing its own task hides its staleness."""
    _story_with_tasks(store)
    _, first = store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    _, again = store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    assert again.claimed_at == first.claimed_at
    assert again.claimed_by_run == "run-alpha"


def test_reclaim_by_the_same_run_still_wins(store):
    """The US-PM-7 idempotent re-claim is not weakened by the new fields."""
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    won, _ = store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    assert won is True


def test_a_new_run_taking_over_the_same_assignee_resets_the_claim(store):
    """A restarted orchestrator retaking "claude"'s work is a genuinely new claim."""
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id="run-alpha")
    old = _backdate_claim(store, "US-TST-1-1", minutes=180)
    won, meta = store.claim_task("US-TST-1-1", "claude", run_id="run-beta")
    assert won is True
    assert meta.claimed_by_run == "run-beta"
    assert meta.claimed_at > old


def test_a_losing_claim_writes_no_metadata(store):
    """The loser leaves the task byte-for-byte untouched, new fields included."""
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "worker-1", run_id="run-alpha")
    path = store.tasks_dir / "US-TST-1-1.md"
    before = path.read_bytes()
    won, current = store.claim_task("US-TST-1-1", "worker-2", run_id="run-beta")
    assert won is False
    assert current.claimed_by_run == "run-alpha"
    assert path.read_bytes() == before


# ═══ 3. pm_grab carries the run id through the tool layer ═══════


def test_pm_grab_records_the_run_id(tmp_project):
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    result = yaml.safe_load(pm_grab("US-TST-1-1", run_id="run-alpha"))
    task = result["grabbed"]["task"]
    assert task["claimed_by_run"] == "run-alpha"
    assert task["claimed_at"] is not None


def test_pm_grab_without_a_run_id_uses_the_process_id(tmp_project):
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    result = yaml.safe_load(pm_grab("US-TST-1-1"))
    assert result["grabbed"]["task"]["claimed_by_run"] == PROCESS_RUN_ID


def test_pm_grab_reclaim_by_the_same_run_is_idempotent(tmp_project):
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    first = yaml.safe_load(pm_grab("US-TST-1-1", run_id="run-alpha"))["grabbed"]["task"]
    again = yaml.safe_load(pm_grab("US-TST-1-1", run_id="run-alpha"))["grabbed"]["task"]
    assert again["claimed_at"] == first["claimed_at"]
    assert again["claimed_by_run"] == first["claimed_by_run"] == "run-alpha"


# ═══ 4. Release and completion clear the claim ══════════════════


def _claimed_task(run_id: str = "run-alpha"):
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1",
        [
            {"title": "Task 1", "description": READY_BODY, "points": 1},
            {"title": "Task 2", "description": READY_BODY, "points": 1},
        ],
    )
    pm_grab("US-TST-1-1", run_id=run_id)


def test_pm_release_clears_both_claim_fields(tmp_project):
    from projectman.server import pm_release

    _claimed_task()
    task = yaml.safe_load(pm_release("US-TST-1-1"))["released"]["task"]
    assert task["assignee"] is None
    assert task["claimed_at"] is None
    assert task["claimed_by_run"] is None


@pytest.mark.parametrize(
    "verb,key", [("pm_retry", "retried"), ("pm_park", "parked"), ("pm_review", "reviewed")]
)
def test_every_verdict_that_releases_clears_the_claim(tmp_project, verb, key):
    import projectman.server as server

    _claimed_task()
    task = yaml.safe_load(getattr(server, verb)("US-TST-1-1", note="why"))[key]["task"]
    assert task["assignee"] is None
    assert task["claimed_at"] is None
    assert task["claimed_by_run"] is None


def test_pm_accept_clears_the_claim_but_keeps_the_assignee(tmp_project):
    """A done task records who did it; a finished claim is not in force."""
    from projectman.server import pm_accept, pm_get

    _claimed_task()
    pm_accept("US-TST-1-1", note="done", next_task=False)
    task = yaml.safe_load(pm_get("US-TST-1-1"))
    assert task["assignee"] == "claude"
    assert task["claimed_at"] is None
    assert task["claimed_by_run"] is None


def test_pm_done_next_clears_the_completed_claim_and_stamps_the_next(tmp_project):
    from projectman.server import pm_done_next, pm_get

    _claimed_task()
    result = yaml.safe_load(
        pm_done_next("US-TST-1-1", note="done", run_id="run-alpha")
    )
    finished = yaml.safe_load(pm_get("US-TST-1-1"))
    assert finished["claimed_at"] is None
    assert finished["claimed_by_run"] is None
    assert result["next"]["task"]["claimed_by_run"] == "run-alpha"


def test_a_released_task_is_claimable_again_with_a_fresh_run(tmp_project):
    from projectman.server import pm_grab, pm_release

    _claimed_task()
    pm_release("US-TST-1-1")
    task = yaml.safe_load(pm_grab("US-TST-1-1", run_id="run-beta"))["grabbed"]["task"]
    assert task["claimed_by_run"] == "run-beta"


# ═══ 5. The activity log carries the run id ═════════════════════


def test_the_claim_event_carries_the_run_id(tmp_project):
    from projectman.server import pm_grab

    _claimed_task(run_id="run-alpha")
    events = [
        e
        for e in _activity(tmp_project)
        if e["item_id"] == "US-TST-1-1" and e.get("run_id") == "run-alpha"
    ]
    assert events, "no claim event carried run-alpha"
    assert any("claimed_by_run" in e.get("changes", {}) for e in events)


def test_the_claim_event_carries_the_timestamp(tmp_project):
    _claimed_task(run_id="run-alpha")
    events = [e for e in _activity(tmp_project) if e.get("run_id") == "run-alpha"]
    changed = [e for e in events if "claimed_at" in e.get("changes", {})]
    assert changed, "no event recorded a claimed_at change"
    assert changed[0]["changes"]["claimed_at"]["before"] is None
    assert changed[0]["changes"]["claimed_at"]["after"]


def test_the_release_event_is_attributed_to_the_run_whose_claim_ended(tmp_project):
    from projectman.server import pm_release

    _claimed_task(run_id="run-alpha")
    pm_release("US-TST-1-1")
    releases = [
        e
        for e in _activity(tmp_project)
        if e.get("run_id") == "run-alpha"
        and e.get("changes", {}).get("claimed_by_run", {}).get("after") is None
    ]
    assert releases, "the release was not attributed to run-alpha"


def test_pm_activity_renders_the_run_id(tmp_project):
    """Stored is not enough — the tool's own output has to show it."""
    from projectman.server import pm_activity

    _claimed_task(run_id="run-alpha")
    body = pm_activity(item_id="US-TST-1-1")
    assert "run run-alpha" in body


def test_pm_activity_does_not_render_a_run_for_an_ordinary_edit(tmp_project):
    from projectman.server import pm_activity, pm_create_story

    pm_create_story("Story", "Story body text long enough to matter.")
    assert "run " not in pm_activity(item_id="US-TST-1")


def test_ordinary_edits_carry_no_run_id(tmp_project):
    """`run_id` means "a run owned this mutation", not "something happened"."""
    from projectman.server import pm_create_story

    pm_create_story("Story", "Story body text long enough to matter.")
    assert all(e.get("run_id") is None for e in _activity(tmp_project))


def test_a_log_line_written_before_run_id_existed_still_parses():
    from projectman.models import LogEntry

    entry = LogEntry(
        **{
            "event_type": "update",
            "item_id": "US-TST-1-1",
            "item_type": "task",
            "changes": {},
            "timestamp": "2026-01-01T00:00:00+00:00",
            "actor": "claude",
            "source": "mcp",
        }
    )
    assert entry.run_id is None


# ═══ 6. Staleness ═══════════════════════════════════════════════


def test_claim_age_is_none_when_the_claim_has_no_timestamp(store):
    _story_with_tasks(store)
    meta, _ = store.get_task("US-TST-1-1")
    assert claim_age_seconds(meta) is None


def test_claim_age_measures_from_the_claim(store):
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude")
    _backdate_claim(store, "US-TST-1-1", minutes=90)
    meta, _ = Store(store.root).get_task("US-TST-1-1")
    assert 89 * 60 < claim_age_seconds(meta) < 91 * 60


@pytest.mark.parametrize(
    "age_minutes,expected", [(1, False), (119, False), (121, True), (600, True)]
)
def test_the_stale_flag_flips_across_the_threshold(store, age_minutes, expected):
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude")
    _backdate_claim(store, "US-TST-1-1", minutes=age_minutes)
    meta, _ = Store(store.root).get_task("US-TST-1-1")
    assert is_stale_claim(meta, 2 * 3600) is expected


def test_a_claim_with_no_timestamp_is_never_stale(store):
    """Unknown age is not old age — legacy files must not be swept up."""
    _story_with_tasks(store)
    store.update("US-TST-1-1", assignee="claude", status="in-progress")
    meta, _ = Store(store.root).get_task("US-TST-1-1")
    assert meta.claimed_at is None
    assert is_stale_claim(meta, 0.0) is False


@pytest.mark.parametrize("status", ["todo", "review", "done"])
def test_only_an_in_progress_task_can_hold_a_stale_claim(store, status):
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude")
    _backdate_claim(store, "US-TST-1-1", minutes=600)
    store.update("US-TST-1-1", status=status)
    meta, _ = Store(store.root).get_task("US-TST-1-1")
    assert is_stale_claim(meta, 2 * 3600) is False


def test_stale_claims_lists_only_the_aged_ones(store):
    _story_with_tasks(store, n_tasks=2)
    store.claim_task("US-TST-1-1", "claude", run_id="run-dead")
    store.claim_task("US-TST-1-2", "claude", run_id="run-live")
    _backdate_claim(store, "US-TST-1-1", minutes=600)
    fresh = Store(store.root)
    assert [t.id for t in fresh.stale_claims()] == ["US-TST-1-1"]


def test_stale_claims_honours_an_explicit_threshold(store):
    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude")
    _backdate_claim(store, "US-TST-1-1", minutes=30)
    fresh = Store(store.root)
    assert fresh.stale_claims() == []
    assert [t.id for t in fresh.stale_claims(max_age_hours=0.25)] == ["US-TST-1-1"]


def test_stale_claims_reads_the_threshold_from_config(store, tmp_project):
    """The default is 2h; `stale_claim_hours` is what a fast pool turns down.

    The config is written *after* the story exists on purpose: `create_story`
    rewrites config.yaml to bump `next_story_id`, so a key set beforehand would
    be overwritten by the fixture rather than by the code under test.
    """
    import yaml as _yaml

    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude")
    _backdate_claim(store, "US-TST-1-1", minutes=30)

    config_path = tmp_project / ".project" / "config.yaml"
    data = _yaml.safe_load(config_path.read_text())
    data["stale_claim_hours"] = 0.25
    config_path.write_text(_yaml.safe_dump(data))

    fresh = Store(store.root)
    assert fresh.config.stale_claim_hours == 0.25
    assert [t.id for t in fresh.stale_claims()] == ["US-TST-1-1"]


# ═══ 7. Staleness surfaces on pm_active / pm_board ══════════════


def test_pm_active_flags_a_stale_claim(tmp_project, store):
    from projectman.server import pm_active

    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id="run-dead")
    _backdate_claim(store, "US-TST-1-1", minutes=600)

    result = yaml.safe_load(pm_active())
    task = result["active_tasks"][0]
    assert task["stale"] is True
    assert task["claimed_by_run"] == "run-dead"
    assert task["claim_age"] > 2 * 3600
    assert result["stale_tasks"] == ["US-TST-1-1"]
    assert result["stale_after_hours"] == 2.0


def test_pm_active_does_not_flag_a_fresh_claim(tmp_project, store):
    from projectman.server import pm_active

    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude", run_id="run-live")

    task = yaml.safe_load(pm_active())["active_tasks"][0]
    assert "stale" not in task
    assert task["claim_age"] < 60


def test_pm_active_stale_after_overrides_the_config(tmp_project, store):
    from projectman.server import pm_active

    _story_with_tasks(store)
    store.claim_task("US-TST-1-1", "claude")
    _backdate_claim(store, "US-TST-1-1", minutes=30)

    assert "stale" not in yaml.safe_load(pm_active())["active_tasks"][0]
    task = yaml.safe_load(pm_active(stale_after=0.25))["active_tasks"][0]
    assert task["stale"] is True


def test_pm_active_leaves_an_unknown_age_claim_alone(tmp_project, store):
    """A task file that predates the fields: no claim_age, no stale flag."""
    from projectman.server import pm_active

    _story_with_tasks(store)
    store.update("US-TST-1-1", assignee="claude", status="in-progress")

    task = yaml.safe_load(pm_active(stale_after=0.0))["active_tasks"][0]
    assert "claim_age" not in task
    assert "stale" not in task


def test_pm_board_flags_and_lists_stale_claims(tmp_project, store):
    from projectman.server import pm_board

    _story_with_tasks(store, n_tasks=2)
    store.claim_task("US-TST-1-1", "claude", run_id="run-dead")
    store.claim_task("US-TST-1-2", "claude", run_id="run-live")
    _backdate_claim(store, "US-TST-1-1", minutes=600)

    result = yaml.safe_load(pm_board())
    by_id = {t["id"]: t for t in result["board"]["in_progress"]}
    assert by_id["US-TST-1-1"]["stale"] is True
    assert by_id["US-TST-1-1"]["claimed_by_run"] == "run-dead"
    assert "stale" not in by_id["US-TST-1-2"]
    # Beside `summary`, not inside it: `summary` is a pinned count-per-group
    # shape (tests/test_task_archived_state.py asserts it whole), and a stale
    # claim is an annotation on in_progress rather than a sixth group.
    assert result["stale_tasks"] == ["US-TST-1-1"]
    assert set(result["summary"]) == {
        "available",
        "not_ready",
        "in_progress",
        "in_review",
        "blocked",
    }
    assert result["stale_after_hours"] == 2.0


# ═══ 8. Back-compat: legacy task files ══════════════════════════


def test_a_task_file_without_the_new_fields_loads(store, tmp_project):
    """The literal on-disk shape from before US-PM-14-5."""
    from projectman.store import clear_all_caches

    legacy = (
        "---\n"
        "id: US-TST-9-1\n"
        "story_id: US-TST-9\n"
        "title: Legacy task\n"
        "status: in-progress\n"
        "points: 1\n"
        "assignee: claude\n"
        "tags: []\n"
        "depends_on: []\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n" + READY_BODY
    )
    (tmp_project / ".project" / "tasks" / "US-TST-9-1.md").write_text(legacy)
    clear_all_caches()

    meta, _ = Store(store.root).get_task("US-TST-9-1")
    assert meta.assignee == "claude"
    assert meta.claimed_at is None
    assert meta.claimed_by_run is None
    assert claim_age_seconds(meta) is None
    assert is_stale_claim(meta, 0.0) is False


def test_a_legacy_task_can_still_be_claimed_and_gains_the_metadata(store, tmp_project):
    from projectman.store import clear_all_caches

    legacy = (
        "---\n"
        "id: US-TST-9-1\n"
        "story_id: US-TST-9\n"
        "title: Legacy task\n"
        "status: todo\n"
        "points: 1\n"
        "tags: []\n"
        "depends_on: []\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n" + READY_BODY
    )
    (tmp_project / ".project" / "tasks" / "US-TST-9-1.md").write_text(legacy)
    clear_all_caches()

    won, meta = Store(store.root).claim_task("US-TST-9-1", "claude", run_id="run-new")
    assert won is True
    assert meta.claimed_by_run == "run-new"
    assert meta.claimed_at is not None


# ═══ 9. Verification (US-PM-14-2) ═══════════════════════════════
#
# Sections 6-8 pin staleness through the Python functions.  This section
# closes the three gaps that verification of "stale claims are identifiable
# without asking a human" turned up, and it asks the question the way an
# orchestrator does: over a real ``tools/call``, so the tool schema, the
# argument coercion and the YAML rendering are all in the path.
#
# * the *boundary* — sections 6-7 test 119 and 121 minutes against a
#   two-hour threshold and never 120, so which side of "exactly at the
#   threshold" is stale was undefined.  It is answered here against a frozen
#   clock, because a wall-clock test of an exact instant is a coin flip.
# * a *malformed threshold* — ``stale_claim_hours: soon`` used to raise out
#   of `load_config`, which is built once per store, so a typo in an optional
#   tuning knob took every tool in the server down with it.
# * *truncation* — ``pm_board(limit=…)`` cuts `in_progress`, and a stale
#   claim that falls off the end must still be named in `stale_tasks` or the
#   flag is only as reliable as the caller's page size.


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


def _ok(name: str, arguments: dict) -> dict:
    """One ``tools/call`` that must succeed, parsed."""
    is_error, text = _call_over_the_wire(name, arguments)
    assert is_error is False, f"{name} failed: {text}"
    return yaml.safe_load(text)


def _set_claimed_at(store: Store, task_id: str, when: datetime) -> None:
    """Write an *exact* `claimed_at` — the boundary needs a precise age."""
    import frontmatter

    from projectman.store import clear_all_caches

    path = store.tasks_dir / f"{task_id}.md"
    post = frontmatter.load(str(path))
    post.metadata["claimed_at"] = when.isoformat()
    path.write_text(frontmatter.dumps(post))
    clear_all_caches()


def _freeze(monkeypatch, when: datetime) -> None:
    """Pin `now` inside `store`, where both staleness helpers read it.

    `claim_age_seconds` and `is_stale_claim` are the only clock readers on
    the staleness path, and `server` imports them by name, so freezing the
    module they live in freezes `pm_active` and `pm_board` alike.
    """
    import projectman.store as store_mod

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return when if tz is not None else when.replace(tzinfo=None)

    monkeypatch.setattr(store_mod, "datetime", _FrozenClock)


def _claimed_and_aged(store, monkeypatch, seconds: float, n_tasks: int = 1):
    """One claimed task whose claim is exactly `seconds` old, clock frozen."""
    _story_with_tasks(store, n_tasks=n_tasks)
    now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(1, n_tasks + 1):
        store.claim_task(f"US-TST-1-{i}", "claude", run_id="run-dead")
        _set_claimed_at(store, f"US-TST-1-{i}", now - timedelta(seconds=seconds))
    _freeze(monkeypatch, now)


# ─── (a) the threshold boundary ──────────────────────────────────


@pytest.mark.parametrize("tool", ["pm_active", "pm_board"])
def test_a_claim_exactly_at_the_threshold_is_not_yet_stale(
    tmp_project, store, monkeypatch, tool
):
    """Documented side of the boundary: the compare is `age > threshold`.

    Exactly two hours old under a two-hour threshold is *not* stale, so a
    threshold reads as "may sit this long", and a claim has to pass it — not
    reach it — to be swept up.
    """
    _claimed_and_aged(store, monkeypatch, seconds=2 * 3600)

    result = _ok(tool, {})
    rendered = (
        result["active_tasks"] if tool == "pm_active" else result["board"]["in_progress"]
    )
    assert rendered[0]["claim_age"] == 2 * 3600
    assert "stale" not in rendered[0]
    assert result["stale_tasks"] == []


@pytest.mark.parametrize("tool", ["pm_active", "pm_board"])
def test_a_claim_one_second_past_the_threshold_is_stale(
    tmp_project, store, monkeypatch, tool
):
    """The other side, one second later — and both tools agree on it."""
    _claimed_and_aged(store, monkeypatch, seconds=2 * 3600 + 1)

    result = _ok(tool, {})
    rendered = (
        result["active_tasks"] if tool == "pm_active" else result["board"]["in_progress"]
    )
    assert rendered[0]["stale"] is True
    assert rendered[0]["claimed_by_run"] == "run-dead"
    assert result["stale_tasks"] == ["US-TST-1-1"]
    assert result["stale_after_hours"] == 2.0


# ─── (b) the threshold is configurable, and junk does not raise ──


@pytest.mark.parametrize("tool", ["pm_active", "pm_board"])
def test_the_config_key_moves_the_threshold_over_the_wire(
    tmp_project, store, monkeypatch, tool
):
    _claimed_and_aged(store, monkeypatch, seconds=30 * 60)
    _write_config_value(tmp_project, 0.25)

    result = _ok(tool, {})
    assert result["stale_after_hours"] == 0.25
    assert result["stale_tasks"] == ["US-TST-1-1"]


@pytest.mark.parametrize("tool", ["pm_active", "pm_board"])
def test_stale_after_overrides_the_config_over_the_wire(
    tmp_project, store, monkeypatch, tool
):
    """The per-call override wins over a config that says otherwise."""
    _claimed_and_aged(store, monkeypatch, seconds=30 * 60)
    _write_config_value(tmp_project, 8.0)

    assert _ok(tool, {})["stale_tasks"] == []
    overridden = _ok(tool, {"stale_after": 0.25})
    assert overridden["stale_after_hours"] == 0.25
    assert overridden["stale_tasks"] == ["US-TST-1-1"]


@pytest.mark.parametrize(
    "junk", ["soon", "", "two hours", "nan", ".inf", -1, [], {"hours": 2}, None]
)
def test_a_malformed_threshold_falls_back_to_the_default(junk):
    """It must not raise: `load_config` builds this model for every tool.

    A value nobody can parse is a typo in an optional tuning knob, and the
    recovery from a typo cannot be "the project stops loading".
    """
    from projectman.models import DEFAULT_STALE_CLAIM_HOURS, ProjectConfig

    config = ProjectConfig(name="t", prefix="TST", stale_claim_hours=junk)
    assert config.stale_claim_hours == DEFAULT_STALE_CLAIM_HOURS


def test_a_meaningful_threshold_is_not_flattened_to_the_default():
    """The fallback must not eat the values a fast pool actually sets."""
    from projectman.models import ProjectConfig

    assert ProjectConfig(name="t", prefix="TST", stale_claim_hours="0.25").stale_claim_hours == 0.25
    assert ProjectConfig(name="t", prefix="TST", stale_claim_hours=0).stale_claim_hours == 0.0


@pytest.mark.parametrize("tool", ["pm_active", "pm_board"])
def test_a_malformed_config_still_answers_the_staleness_question(
    tmp_project, store, monkeypatch, tool
):
    """End to end: junk in config.yaml, the default on the wire, no error."""
    _claimed_and_aged(store, monkeypatch, seconds=10 * 3600)
    _write_config_value(tmp_project, "soon")

    result = _ok(tool, {})
    assert result["stale_after_hours"] == 2.0
    assert result["stale_tasks"] == ["US-TST-1-1"]


# ─── (e) the flag survives pm_board's truncation ─────────────────


def test_a_stale_claim_past_the_board_limit_is_still_counted(
    tmp_project, store, monkeypatch
):
    """`limit` pages `in_progress`; `stale_tasks` is the whole answer.

    An orchestrator that released only what it could see on page one would
    leave the rest of a dead run's claims sitting forever.
    """
    _claimed_and_aged(store, monkeypatch, seconds=10 * 3600, n_tasks=5)

    result = _ok("pm_board", {"limit": 2})
    rendered = [t["id"] for t in result["board"]["in_progress"]]
    assert len(rendered) == 2
    assert result["summary"]["in_progress"] == 5
    assert sorted(result["stale_tasks"]) == [f"US-TST-1-{i}" for i in range(1, 6)]
    assert [i for i in result["stale_tasks"] if i not in rendered], (
        "the truncation never dropped a stale task, so this proves nothing"
    )
