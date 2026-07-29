"""Sprint velocity may only count genuinely delivered points (US-PM-16-3).

``Store.update_sprint`` auto-computes ``completed_points`` when a sprint is
closed, and that number *is* the team's velocity: ``/pm-orchestrate``'s
sprint close-out step calls ``pm_update_sprint(status="completed")`` and
reports the result as what the next sprint gets sized against.  Before
US-PM-16-6 the computation read ``if story_meta.status.value in ("done",
"archived")`` — an abandoned story was literally counted as delivered, so a
cleanup pass inflated velocity and silently mis-sized every future sprint.

``tests/test_archived_excluded_from_metrics.py`` already pins the simple
shapes (archived-only, done-only, all-archived, and ``pm_update_sprint``'s
response).  This module covers what those leave open:

* a *mixed* sprint — delivered, abandoned and still-open stories together —
  asserted against the one exact number, since with only two stories several
  wrong implementations happen to produce the right answer;
* recompute and idempotency, which the surviving-number surfaces depend on:
  what a *second* close does, what any later edit to a closed sprint does, and
  what plain reads report in between;
* degenerate inputs — unpointed stories, an empty sprint, a planned story that
  no longer exists — which must yield a number rather than an exception,
  because ``update_sprint`` swallows per-story errors and a crash here would
  instead abort the close-out;
* the story/task boundary: story points are the unit of velocity, so archived
  *tasks* under a delivered story must not shave it down;
* ``pm_get_sprint`` and ``pm_list_sprints``, the read surfaces a caller
  actually reads the velocity number back from.

A genuinely ``done`` story is the control in every test: an implementation
that reported zero velocity would satisfy "archived does not count" and must
still fail here.
"""

import yaml


# ─── Helpers ─────────────────────────────────────────────────────


def _mcp(tmp_project, monkeypatch):
    """Point the MCP tool layer at the temp project with a cold cache."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()


# ─── The regression, at full sprint shape ────────────────────────


class TestMixedSprintVelocity:
    """A real sprint holds delivered, abandoned and unfinished work at once."""

    def test_mixed_sprint_counts_only_the_delivered_stories(self, store):
        """8 delivered + 13 abandoned + 5 unfinished must read exactly 8.

        The pre-fix code returned 21 here.  Asserting the exact number is the
        point: "less than 21" also passes for 0, which would mean velocity had
        simply been zeroed out.
        """
        store.create_story("Delivered A", "Desc", points=5)  # US-TST-1
        store.create_story("Delivered B", "Desc", points=3)  # US-TST-2
        store.create_story("Abandoned", "Desc", points=13)  # US-TST-3
        store.create_story("Still open", "Desc", points=5)  # US-TST-4
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.archive("US-TST-3")
        store.update("US-TST-4", status="active")
        store.create_sprint(
            "Sprint 1",
            planned_stories=["US-TST-1", "US-TST-2", "US-TST-3", "US-TST-4"],
        )

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 8

    def test_planned_points_still_include_everything_that_was_committed(
        self, store
    ):
        """Velocity drops the abandoned story; the *commitment* it was planned
        against does not silently shrink with it, so the miss stays visible."""
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Abandoned", "Desc", points=13)
        store.update("US-TST-1", status="done")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 5
        assert meta.planned_points == 18
        assert meta.planned_points > meta.completed_points

    def test_velocity_never_exceeds_what_was_planned(self, store):
        """The pre-fix bug could not be caught by a range check alone, but a
        velocity above the commitment is unambiguously corrupt."""
        store.create_story("Delivered", "Desc", points=8)
        store.create_story("Abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 8
        assert 0 <= meta.completed_points <= meta.planned_points


# ─── Recompute and idempotency ───────────────────────────────────


class TestVelocityRecomputeIsStable:
    """Sprint close-out is not guaranteed to run exactly once — an orchestrator
    can retry it, and a closed sprint can still be edited afterwards."""

    def test_closing_an_already_closed_sprint_does_not_drift(self, store):
        """Velocity accumulates into a field; a ``+=`` against the stored value
        instead of a fresh sum would double on the second close."""
        store.create_story("A", "Desc", points=5)
        store.create_story("B", "Desc", points=3)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        first = store.update_sprint("SPRINT-TST-1", status="completed")
        second = store.update_sprint("SPRINT-TST-1", status="completed")
        third = store.update_sprint("SPRINT-TST-1", status="completed")

        assert first.completed_points == 8
        assert second.completed_points == 8
        assert third.completed_points == 8

    def test_reclosing_after_a_story_is_archived_drops_its_credit(self, store):
        """A closed sprint that is closed again after /pm-cleanup ran must
        recompute downward, not keep the credit it already banked."""
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Later abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])
        assert store.update_sprint("SPRINT-TST-1", status="completed").completed_points == 13

        store.archive("US-TST-2")

        assert store.update_sprint("SPRINT-TST-1", status="completed").completed_points == 5

    def test_a_plain_read_reports_the_number_banked_at_close(self, store):
        """Pinning observed behaviour: ``get_sprint`` does not recompute.

        Archiving a story *after* the sprint closed leaves the stored velocity
        untouched until something writes the sprint again.  That is defensible
        — a closed sprint's velocity is a historical record — but it means the
        number a reader sees can disagree with what a re-close would produce,
        so it is pinned rather than left to chance.
        """
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Later abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])
        store.update_sprint("SPRINT-TST-1", status="completed")

        store.archive("US-TST-2")

        assert store.get_sprint("SPRINT-TST-1")[0].completed_points == 13
        assert store.update_sprint("SPRINT-TST-1", status="completed").completed_points == 5

    def test_any_edit_to_a_closed_sprint_recomputes_velocity(self, store):
        """Pinning observed behaviour: the recompute is keyed off the sprint's
        *current* status, not off this call changing it.

        Renaming a closed sprint therefore rewrites its velocity from live
        story state.  What matters for US-PM-16 is that this incidental path
        also excludes archived work — otherwise a cosmetic edit months later
        could quietly re-credit abandoned stories.
        """
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Later abandoned", "Desc", points=8)
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])
        store.update_sprint("SPRINT-TST-1", status="completed")

        store.archive("US-TST-2")
        meta = store.update_sprint("SPRINT-TST-1", name="Sprint One (renamed)")

        assert meta.name == "Sprint One (renamed)"
        assert meta.completed_points == 5

    def test_adding_a_story_to_a_closed_sprint_credits_only_delivery(
        self, store
    ):
        """``planned_stories`` edits recalculate both numbers in one pass."""
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Abandoned", "Desc", points=8)
        store.create_story("Also delivered", "Desc", points=3)
        store.update("US-TST-1", status="done")
        store.update("US-TST-3", status="done")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1"])
        store.update_sprint("SPRINT-TST-1", status="completed")

        meta = store.update_sprint(
            "SPRINT-TST-1", planned_stories=["US-TST-1", "US-TST-2", "US-TST-3"]
        )

        assert meta.completed_points == 8
        assert meta.planned_points == 16


# ─── Degenerate inputs ───────────────────────────────────────────


class TestVelocityDegenerateInputs:
    """Close-out must produce a number, never an exception."""

    def test_unpointed_stories_contribute_nothing_and_do_not_crash(self, store):
        store.create_story("Unpointed delivered", "Desc")
        store.create_story("Pointed delivered", "Desc", points=3)
        assert store.get_story("US-TST-1")[0].points is None
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 3

    def test_an_unpointed_archived_story_is_still_excluded(self, store):
        store.create_story("Delivered", "Desc", points=5)
        store.create_story("Unpointed abandoned", "Desc")
        store.update("US-TST-1", status="done")
        store.update("US-TST-2", status="done")
        store.archive("US-TST-2")
        store.create_sprint("Sprint 1", planned_stories=["US-TST-1", "US-TST-2"])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 5

    def test_a_sprint_with_no_planned_stories_reports_zero_velocity(self, store):
        store.create_sprint("Empty sprint")

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 0
        assert meta.planned_points == 0

    def test_a_planned_story_that_no_longer_exists_is_skipped(self, store):
        """Deleted or renamed stories must not abort the close-out."""
        store.create_story("Delivered", "Desc", points=5)
        store.update("US-TST-1", status="done")
        store.create_sprint(
            "Sprint 1", planned_stories=["US-TST-1", "US-TST-404"]
        )

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 5


# ─── The story/task boundary ─────────────────────────────────────


class TestVelocityUsesStoryPointsNotTaskPoints:
    """Velocity is measured in story points.  Task-level archiving changes how
    a story's *progress* reads, but a delivered story is delivered in full."""

    def test_a_delivered_story_counts_in_full_despite_archived_tasks(
        self, store
    ):
        """The story was accepted as done; abandoning one of its tasks along
        the way does not retroactively make it a partial delivery.  Counting
        3 of 5 here would under-report velocity just as badly as the original
        bug over-reported it."""
        story, _ = store.create_story("Delivered", "Desc", points=5)
        done_task = store.create_task(story.id, "Kept", "D" * 80, points=3)
        dropped_task = store.create_task(story.id, "Dropped", "D" * 80, points=2)
        store.update(done_task.id, status="done")
        store.archive(dropped_task.id)
        store.update(story.id, status="done")
        store.create_sprint("Sprint 1", planned_stories=[story.id])

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 5

    def test_an_archived_story_with_done_tasks_contributes_nothing(self, store):
        """The mirror image: work genuinely finished underneath a story that
        was then abandoned does not leak back in through the task layer."""
        store.create_story("Delivered", "Desc", points=3)
        store.update("US-TST-1", status="done")
        story, _ = store.create_story("Abandoned", "Desc", points=13)
        task = store.create_task(story.id, "Finished anyway", "D" * 80, points=8)
        store.update(task.id, status="done")
        store.update(story.id, status="done")
        store.archive(story.id)
        store.create_sprint(
            "Sprint 1", planned_stories=["US-TST-1", story.id]
        )

        meta = store.update_sprint("SPRINT-TST-1", status="completed")

        assert meta.completed_points == 3


# ─── Read surfaces ───────────────────────────────────────────────


class TestVelocityReadSurfaces:
    """Whatever a caller reads the number back from must agree with the close."""

    def test_pm_get_sprint_reports_delivered_points_only(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_sprint,
            pm_create_story,
            pm_get_sprint,
            pm_update,
            pm_update_sprint,
        )

        pm_create_story("Delivered", "Desc", points=5)
        pm_create_story("Abandoned", "Desc", points=13)
        pm_create_story("Still open", "Desc", points=3)
        pm_update("US-TST-1", status="done")
        pm_update("US-TST-2", status="done")
        pm_archive("US-TST-2")
        pm_create_sprint(
            "Sprint 1", planned_stories="US-TST-1,US-TST-2,US-TST-3"
        )
        pm_update_sprint("SPRINT-TST-1", status="completed")

        result = yaml.safe_load(pm_get_sprint("SPRINT-TST-1"))

        assert result["completed_points"] == 5
        assert result["planned_points"] == 21

    def test_pm_list_sprints_reports_delivered_points_only(
        self, tmp_project, monkeypatch
    ):
        """The velocity a planner reads when sizing the next sprint comes from
        the history list, not from the close-out response."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_sprint,
            pm_create_story,
            pm_list_sprints,
            pm_update,
            pm_update_sprint,
        )

        pm_create_story("Delivered", "Desc", points=5)
        pm_create_story("Abandoned", "Desc", points=13)
        pm_update("US-TST-1", status="done")
        pm_update("US-TST-2", status="done")
        pm_archive("US-TST-2")
        pm_create_sprint("Sprint 1", planned_stories="US-TST-1,US-TST-2")
        pm_update_sprint("SPRINT-TST-1", status="completed")

        result = yaml.safe_load(pm_list_sprints(status="completed"))

        assert result["count"] == 1
        assert result["sprints"][0]["completed_points"] == 5

    def test_average_velocity_across_sprints_is_not_inflated(
        self, tmp_project, monkeypatch
    ):
        """Sizing usually averages the last few sprints, so an inflated close
        keeps distorting plans long after the sprint it happened in."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_create_sprint,
            pm_create_story,
            pm_list_sprints,
            pm_update,
            pm_update_sprint,
        )

        # Sprint 1: 5 delivered, 13 abandoned.
        pm_create_story("S1 delivered", "Desc", points=5)
        pm_create_story("S1 abandoned", "Desc", points=13)
        pm_update("US-TST-1", status="done")
        pm_update("US-TST-2", status="done")
        pm_archive("US-TST-2")
        pm_create_sprint("Sprint 1", planned_stories="US-TST-1,US-TST-2")
        pm_update_sprint("SPRINT-TST-1", status="completed")

        # Sprint 2: 3 delivered, nothing abandoned.
        pm_create_story("S2 delivered", "Desc", points=3)
        pm_update("US-TST-3", status="done")
        pm_create_sprint("Sprint 2", planned_stories="US-TST-3")
        pm_update_sprint("SPRINT-TST-2", status="completed")

        sprints = yaml.safe_load(pm_list_sprints(status="completed"))["sprints"]
        points = sorted(s["completed_points"] for s in sprints)

        assert points == [3, 5]
        assert sum(points) / len(points) == 4
