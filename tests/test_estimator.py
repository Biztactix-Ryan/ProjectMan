"""Tests for estimation support."""

import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from projectman.store import Store
from projectman.estimator import estimate
from projectman.errors import NotFoundError
from projectman.scoper import scope


def test_estimate_story(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "As a user, I want login")
    result = estimate(store, "US-TST-1")
    data = yaml.safe_load(result)
    assert "estimation_guidance" in data
    assert "fibonacci_scale" in data["estimation_guidance"]


def test_estimate_with_history(tmp_project):
    store = Store(tmp_project)
    store.create_story("Done Story", "Desc", points=5)
    store.update("US-TST-1", status="done")
    store.create_story("New Story", "Desc")
    result = estimate(store, "US-TST-2")
    data = yaml.safe_load(result)
    assert data["estimation_guidance"]["historical_average"] == 5.0


# ─── Edge cases (US-PRJ-64-5) ──────────────────────────────────────
#
# ``estimate()`` builds its "historical_average" from
# ``store.list_stories(status="done")`` and averages only the *pointed*
# ones, so the tests below pin down each of the four ways that input can
# be unusual: nothing to average, a lot to average, statuses that look
# done but are not counted, and an ID that does not resolve at all.


def test_empty_history_returns_no_data_without_raising(tmp_project):
    """No done stories at all: guidance still renders, average says "no data"."""
    store = Store(tmp_project)
    store.create_story("Only Story", "Nothing is done yet", points=3)

    result = estimate(store, "US-TST-1")
    data = yaml.safe_load(result)

    guidance = data["estimation_guidance"]
    assert guidance["historical_average"] == "no data"
    assert guidance["fibonacci_scale"] == [1, 2, 3, 5, 8, 13]
    assert set(guidance["calibration"]) == {1, 2, 3, 5, 8, 13}
    assert data["current_points"] == 3


def test_empty_history_when_done_stories_are_all_unpointed(tmp_project):
    """The other empty history: done stories exist, none carries points.

    ``estimate`` filters on ``if s.points``, so an unpointed done story
    contributes nothing and the average falls back to "no data" exactly as
    it does with no done stories at all.
    """
    store = Store(tmp_project)
    store.create_story("Done But Unpointed", "Desc")
    store.update("US-TST-1", status="done")
    store.create_story("Target", "Desc")

    data = yaml.safe_load(estimate(store, "US-TST-2"))
    assert data["estimation_guidance"]["historical_average"] == "no data"


def test_large_history_20_plus_done_stories_averages_all_points(tmp_project):
    """22 done stories with mixed points: the average covers every one."""
    store = Store(tmp_project)
    cycle = [1, 2, 3, 5, 8, 13]
    points = [cycle[i % len(cycle)] for i in range(22)]

    for i, p in enumerate(points, start=1):
        store.create_story(f"Done {i}", "Desc", points=p)
        store.update(f"US-TST-{i}", status="done")

    store.create_story("Target", "Estimate me")
    target_id = f"US-TST-{len(points) + 1}"

    assert len(store.list_stories(status="done")) == 22

    data = yaml.safe_load(estimate(store, target_id))
    expected = round(sum(points) / len(points), 1)
    assert data["estimation_guidance"]["historical_average"] == expected
    # Sanity: a real mean of a genuinely mixed distribution (107/22 = 4.86,
    # rounded to one decimal), not a single repeated value.
    assert len(set(points)) == 6
    assert expected == 4.9


def test_large_history_20_plus_ignores_unpointed_done_stories(tmp_project):
    """Unpointed done stories are not in the denominator of the average."""
    store = Store(tmp_project)
    for i in range(1, 21):
        store.create_story(f"Pointed {i}", "Desc", points=8)
        store.update(f"US-TST-{i}", status="done")
    for i in range(21, 26):
        store.create_story(f"Unpointed {i}", "Desc")
        store.update(f"US-TST-{i}", status="done")

    store.create_story("Target", "Estimate me")

    assert len(store.list_stories(status="done")) == 25
    data = yaml.safe_load(estimate(store, "US-TST-26"))
    # 20 x 8 points averaged over 20, not over 25.
    assert data["estimation_guidance"]["historical_average"] == 8.0


def test_mixed_statuses_count_only_done_stories(tmp_project):
    """done / backlog / active / archived: only ``status: done`` is averaged.

    ``estimate`` asks for ``list_stories(status="done")``, and an archived
    story carries ``status: archived`` (``Store.archive`` overwrites the
    status for stories) — so a story that was done and then archived drops
    out of the history entirely.  That is current behaviour, documented here.
    """
    store = Store(tmp_project)
    store.create_story("Done A", "Desc", points=2)
    store.update("US-TST-1", status="done")
    store.create_story("Done B", "Desc", points=8)
    store.update("US-TST-2", status="done")

    store.create_story("Backlog", "Desc", points=13)  # US-TST-3, left in backlog

    store.create_story("Active", "Desc", points=13)
    store.update("US-TST-4", status="active")

    store.create_story("Archived Done", "Desc", points=13)
    store.update("US-TST-5", status="done")
    store.archive("US-TST-5")  # status becomes "archived", no longer "done"

    store.create_story("Target", "Estimate me")

    done = store.list_stories(status="done")
    assert sorted(s.id for s in done) == ["US-TST-1", "US-TST-2"]

    data = yaml.safe_load(estimate(store, "US-TST-6"))
    # (2 + 8) / 2 — the 13-pointers in backlog/active/archived are excluded.
    assert data["estimation_guidance"]["historical_average"] == 5.0


def test_mixed_statuses_tasks_do_not_affect_story_history(tmp_project):
    """Only stories feed the average; a done, pointed task changes nothing."""
    store = Store(tmp_project)
    store.create_story("Done Story", "Desc", points=2)
    store.update("US-TST-1", status="done")
    store.create_task("US-TST-1", "Done Task", "Desc", points=13)
    store.update("US-TST-1-1", status="done")

    store.create_story("Target", "Estimate me")

    data = yaml.safe_load(estimate(store, "US-TST-2"))
    assert data["estimation_guidance"]["historical_average"] == 2.0


def test_unknown_story_id_raises_not_found_error(tmp_project):
    """An unresolvable story ID surfaces the store's coded not-found error."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")

    with pytest.raises(NotFoundError) as exc_info:
        estimate(store, "US-TST-99")

    assert exc_info.value.code == "not_found"
    assert "US-TST-99" in str(exc_info.value)
    # Back-compat: NotFoundError is also a FileNotFoundError.
    assert isinstance(exc_info.value, FileNotFoundError)


def test_unknown_task_id_raises_not_found_error(tmp_project):
    """The task branch of ``Store.get`` raises the same coded error."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")

    with pytest.raises(NotFoundError) as exc_info:
        estimate(store, "US-TST-1-9")

    assert exc_info.value.code == "not_found"
    assert "US-TST-1-9" in str(exc_info.value)


def test_estimate_accepts_a_task_id(tmp_project):
    """A task ID resolves through ``Store.get`` and reports the task's points."""
    store = Store(tmp_project)
    store.create_story("Parent", "Desc")
    store.create_task("US-TST-1", "A Task", "Task body here", points=2)

    data = yaml.safe_load(estimate(store, "US-TST-1-1"))

    assert data["item"]["id"] == "US-TST-1-1"
    assert data["item"]["story_id"] == "US-TST-1"
    assert data["current_points"] == 2
    assert data["body"].strip() == "Task body here"
    assert data["estimation_guidance"]["fibonacci_scale"] == [1, 2, 3, 5, 8, 13]


def test_estimate_accepts_a_story_id(tmp_project):
    """The story branch returns the story's own metadata and body."""
    store = Store(tmp_project)
    store.create_story("A Story", "Story body here", points=5)

    data = yaml.safe_load(estimate(store, "US-TST-1"))

    assert data["item"]["id"] == "US-TST-1"
    assert "story_id" not in data["item"]
    assert data["current_points"] == 5
    assert data["body"].strip() == "Story body here"


# ─── duration_history beside the guidance (US-PM-50-8) ─────────────
#
# ``pm_estimate`` and ``pm_scope`` are where sizing decisions are made, so
# both carry the project's measured grab-to-done history next to the advice
# they already gave.  The activity log is written by hand here for the same
# reason ``test_duration_history.py`` writes it by hand: these tests are
# about what the two tools *report*, not about the store's write path.

_BASE = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


def _event(item_id, after, minute):
    """One orchestrated status transition, ``minute`` minutes after _BASE."""
    return json.dumps(
        {
            "event_type": "update",
            "item_id": item_id,
            "item_type": "task",
            "changes": {"status": {"before": None, "after": after}},
            "timestamp": (_BASE + timedelta(minutes=minute))
            .isoformat()
            .replace("+00:00", "Z"),
            "run_id": "orch-2026-09-09-1",
            "actor": "tester",
            "source": "cli",
        }
    )


def _seed_durations(store, stretches):
    """Give ``store`` one measurable stretch per ``(task_id, minutes)`` pair."""
    lines = []
    for offset, (task_id, minutes) in enumerate(stretches):
        start = offset * 1000
        lines.append(_event(task_id, "in-progress", start))
        lines.append(_event(task_id, "done", start + minutes))
    (store.project_dir / "activity.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture
def three_pointers(tmp_project):
    """A store whose three 3-point tasks took 10, 20 and 90 minutes."""
    store = Store(tmp_project)
    store.create_story("Story", "A story to hang tasks off")
    for n in range(3):
        store.create_task("US-TST-1", f"Task {n}", "d", points=3)
    _seed_durations(
        store,
        [("US-TST-1-1", 10), ("US-TST-1-2", 20), ("US-TST-1-3", 90)],
    )
    return store


@pytest.mark.parametrize("render", [estimate, scope])
def test_both_tools_carry_a_duration_history_block(three_pointers, render):
    """pm_estimate and pm_scope both report the block beside their guidance."""
    data = yaml.safe_load(render(three_pointers, "US-TST-1"))

    history = data["duration_history"]
    assert set(history) == {"by_points", "n", "max_task_minutes"}
    assert history["n"] == 3
    assert history["by_points"][3] == {"p50": 20.0, "p90": 90.0, "max": 90.0, "n": 3}


@pytest.mark.parametrize("render", [estimate, scope])
def test_the_block_sits_beside_the_existing_guidance(three_pointers, render):
    """Adding it displaces nothing: the old keys are all still there."""
    data = yaml.safe_load(render(three_pointers, "US-TST-1"))

    assert "duration_history" in data
    if render is estimate:
        assert "fibonacci_scale" in data["estimation_guidance"]
    else:
        assert "rules" in data["decomposition_guidance"]


@pytest.mark.parametrize("render", [estimate, scope])
def test_bands_are_reported_per_points_value(tmp_project, render):
    """Two point values, two bands — each with its own p50/p90/n."""
    store = Store(tmp_project)
    store.create_story("Story", "Mixed sizes")
    store.create_task("US-TST-1", "Small", "d", points=1)  # -1
    store.create_task("US-TST-1", "Small too", "d", points=1)  # -2
    store.create_task("US-TST-1", "Big", "d", points=5)  # -3
    _seed_durations(
        store,
        [("US-TST-1-1", 5), ("US-TST-1-2", 15), ("US-TST-1-3", 120)],
    )

    bands = yaml.safe_load(render(store, "US-TST-1"))["duration_history"]["by_points"]

    assert set(bands) == {1, 5}
    assert bands[1] == {"p50": 5.0, "p90": 15.0, "max": 15.0, "n": 2}
    assert bands[5] == {"p50": 120.0, "p90": 120.0, "max": 120.0, "n": 1}


@pytest.mark.parametrize("render", [estimate, scope])
def test_the_threshold_defaults_to_sixty_minutes(three_pointers, render):
    """With nothing configured, the reported ceiling is the default hour."""
    data = yaml.safe_load(render(three_pointers, "US-TST-1"))

    assert data["duration_history"]["max_task_minutes"] == 60


@pytest.mark.parametrize("render", [estimate, scope])
def test_the_threshold_reflects_config(tmp_project, render):
    """`orchestrate.max_task_minutes` in config.yaml is what comes back."""
    config_path = tmp_project / ".project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["orchestrate"] = {"max_task_minutes": 25}
    config_path.write_text(yaml.dump(config))

    store = Store(tmp_project)
    store.create_story("Story", "Desc")

    data = yaml.safe_load(render(store, "US-TST-1"))

    assert data["duration_history"]["max_task_minutes"] == 25


@pytest.mark.parametrize("render", [estimate, scope])
def test_a_thin_history_says_so(tmp_project, render):
    """Under three measured tasks the block warns rather than implying a rule."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")
    store.create_task("US-TST-1", "Only one", "d", points=3)
    _seed_durations(store, [("US-TST-1-1", 45)])

    history = yaml.safe_load(render(store, "US-TST-1"))["duration_history"]

    assert history["n"] == 1
    assert "too thin to flag long tasks" in history["note"]


@pytest.mark.parametrize("render", [estimate, scope])
def test_an_empty_history_says_so_too(tmp_project, render):
    """No activity log at all: empty bands, n of 0, and the same note."""
    store = Store(tmp_project)
    store.create_story("Story", "Desc")

    history = yaml.safe_load(render(store, "US-TST-1"))["duration_history"]

    assert history["by_points"] == {}
    assert history["n"] == 0
    assert "too thin" in history["note"]


@pytest.mark.parametrize("render", [estimate, scope])
def test_no_note_once_three_tasks_have_been_measured(three_pointers, render):
    """At the threshold the note goes away — three samples is a history."""
    history = yaml.safe_load(render(three_pointers, "US-TST-1"))["duration_history"]

    assert history["n"] == 3
    assert "note" not in history


def test_estimate_reports_the_history_for_a_task_id_too(three_pointers):
    """The block is the project's, not the item's, so a task ID gets it as well."""
    data = yaml.safe_load(estimate(three_pointers, "US-TST-1-1"))

    assert data["duration_history"]["n"] == 3
