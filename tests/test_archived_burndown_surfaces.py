"""Every surface that reports progress must drop archived work (US-PM-16-2).

``tests/test_archived_excluded_from_metrics.py`` pins the rule where it is
implemented — ``build_index`` — and at ``pm_status``, ``pm_burndown``,
``pm_epic`` and sprint velocity.  This module covers what that leaves open:

* the *internal consistency* of the burndown numbers, not just their values —
  ``remaining == total - completed`` and a completion percentage that stays
  inside 0-100%;
* the web ``/api/status`` and ``/api/burndown`` routes, which re-implement the
  same arithmetic in ``web/routes/api.py`` rather than calling the MCP tools,
  so they can drift independently (covered in ``tests/web/``);
* the hub rollup, which sums ``build_index`` across subprojects and feeds both
  hub-mode ``pm_burndown`` and the generated ``burndown.md`` dashboard;
* archived epics, whose exclusion runs through a *different* mechanism
  (``list_epics`` drops them before ``build_index`` ever sees them).

The wrong implementation these tests exist to catch is the half-fix: dropping
archived work from the denominator but still crediting it in the numerator.
That reads as "the abandoned work is no longer owed" while continuing to claim
it as delivered, and with enough archived-after-done work it drives
``remaining_points`` negative and completion past 100%.  A genuinely ``done``
task is the control throughout — a fix that simply excluded everything would
be just as wrong and must fail these tests too.
"""

import yaml

from projectman.indexer import build_index


# ─── Helpers ─────────────────────────────────────────────────────


def _mcp(tmp_project, monkeypatch):
    """Point the MCP tool layer at the temp project with a cold cache."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()


def _mixed_project():
    """A project holding one of every shape work can be in.

    Delivered 5, still outstanding 3, abandoned-while-todo 2, and — the shape
    that lies — abandoned *after* being marked done, 8.  Honest arithmetic:
    total 8, completed 5, remaining 3.
    """
    from projectman.server import (
        pm_archive,
        pm_create_story,
        pm_create_task,
        pm_update,
    )

    pm_create_story("Story", "Desc")
    pm_create_task("US-TST-1", "Delivered", "A" * 80, points=5)
    pm_create_task("US-TST-1", "Outstanding", "A" * 80, points=3)
    pm_create_task("US-TST-1", "Abandoned mid-flight", "A" * 80, points=2)
    pm_create_task("US-TST-1", "Abandoned after done", "A" * 80, points=8)
    pm_update("US-TST-1-1", status="done")
    pm_update("US-TST-1-4", status="done")
    pm_archive("US-TST-1-3")
    pm_archive("US-TST-1-4")


def _register_subproject(hub_root, name, prefix="SUB"):
    """Set up a hub subproject with a source dir, PM data dir, and config entry."""
    import yaml as _yaml

    from projectman.config import load_config, save_config

    (hub_root / "projects" / name).mkdir(parents=True, exist_ok=True)

    pm_dir = hub_root / ".project" / "projects" / name
    pm_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("stories", "tasks", "epics"):
        (pm_dir / sub).mkdir(exist_ok=True)

    with open(pm_dir / "config.yaml", "w") as f:
        _yaml.dump(
            {
                "name": name,
                "prefix": prefix,
                "description": "",
                "hub": False,
                "next_story_id": 1,
                "next_epic_id": 1,
                "projects": [],
            },
            f,
        )

    hub_config = load_config(hub_root)
    if name not in hub_config.projects:
        hub_config.projects.append(name)
        save_config(hub_config, hub_root)

    return pm_dir


# ─── Burndown arithmetic holds together ──────────────────────────


class TestBurndownNumbersStayConsistent:
    """``pm_burndown`` publishes total, completed and remaining together.

    Checking the three values individually is not enough: a half-fix can
    produce a plausible-looking total and a plausible-looking completed while
    the relationship between them has become nonsense.
    """

    def test_remaining_is_exactly_total_minus_completed(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import pm_burndown

        _mixed_project()

        result = yaml.safe_load(pm_burndown())
        assert result["total_points"] == 8
        assert result["completed_points"] == 5
        assert result["remaining_points"] == 3
        assert (
            result["remaining_points"]
            == result["total_points"] - result["completed_points"]
        )

    def test_abandoned_delivery_cannot_drive_remaining_negative(
        self, tmp_project, monkeypatch
    ):
        """The half-fix signature: 8 archived-after-done points credited as
        delivered against a denominator they have already left."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import pm_burndown

        _mixed_project()

        result = yaml.safe_load(pm_burndown())
        assert result["remaining_points"] >= 0
        assert result["completed_points"] <= result["total_points"]

    def test_completion_stays_within_a_hundred_percent(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import pm_burndown

        _mixed_project()

        pct = int(yaml.safe_load(pm_burndown())["completion"].rstrip("%"))
        assert 0 <= pct <= 100
        assert pct == 62  # 5 of 8, rounded

    def test_a_wholly_abandoned_project_burns_down_to_nothing(
        self, tmp_project, monkeypatch
    ):
        """Denominator zero.  Must not raise, and must not claim completion."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_archive,
            pm_burndown,
            pm_create_story,
            pm_create_task,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Abandoned", "A" * 80, points=5)
        pm_create_task("US-TST-1", "Abandoned too", "A" * 80, points=3)
        pm_update("US-TST-1-1", status="done")
        pm_archive("US-TST-1-1")
        pm_archive("US-TST-1-2")

        result = yaml.safe_load(pm_burndown())
        assert result["total_points"] == 0
        assert result["completed_points"] == 0
        assert result["remaining_points"] == 0
        assert result["completion"] == "0%"

    def test_a_fully_delivered_project_still_reports_complete(
        self, tmp_project, monkeypatch
    ):
        """Control: excluding *everything* would satisfy the tests above."""
        _mcp(tmp_project, monkeypatch)
        from projectman.server import (
            pm_burndown,
            pm_create_story,
            pm_create_task,
            pm_update,
        )

        pm_create_story("Story", "Desc")
        pm_create_task("US-TST-1", "Delivered", "A" * 80, points=5)
        pm_create_task("US-TST-1", "Delivered too", "A" * 80, points=3)
        pm_update("US-TST-1-1", status="done")
        pm_update("US-TST-1-2", status="done")

        result = yaml.safe_load(pm_burndown())
        assert result["total_points"] == 8
        assert result["completed_points"] == 8
        assert result["remaining_points"] == 0
        assert result["completion"] == "100%"


class TestStatusAndBurndownDoNotDisagree:
    """Both tools derive their points from the same ``build_index`` call.

    Pinned so that a future surface-local "fix" to one of them — the obvious
    way for the two to drift — shows up as a failure here.
    """

    def test_pm_status_and_pm_burndown_report_the_same_points(
        self, tmp_project, monkeypatch
    ):
        _mcp(tmp_project, monkeypatch)
        from projectman.server import pm_burndown, pm_status

        _mixed_project()

        status = yaml.safe_load(pm_status())
        burndown = yaml.safe_load(pm_burndown())

        assert status["total_points"] == burndown["total_points"] == 8
        assert status["completed_points"] == burndown["completed_points"] == 5
        assert status["completion"] == burndown["completion"]


# ─── Hub rollup ──────────────────────────────────────────────────


class TestHubRollupExcludesArchived:
    """Hub-mode ``pm_burndown`` returns ``rollup()`` verbatim, and the
    generated ``burndown.md`` dashboard is rendered from the same dict, so
    archived work leaking in here corrupts the whole-portfolio view."""

    def _subproject_store(self, tmp_hub, name="api", prefix="API"):
        from projectman.store import Store, _cache

        pm_dir = _register_subproject(tmp_hub, name, prefix=prefix)
        _cache.clear()
        return Store(tmp_hub, project_dir=pm_dir)

    def test_rollup_drops_archived_points_from_both_sides(self, tmp_hub):
        store = self._subproject_store(tmp_hub)
        story, _ = store.create_story("Story", "Desc")
        delivered = store.create_task(story.id, "Delivered", "D" * 40, points=5)
        outstanding = store.create_task(story.id, "Outstanding", "D" * 40, points=3)
        abandoned = store.create_task(story.id, "Abandoned", "D" * 40, points=8)
        store.update(delivered.id, status="done")
        store.update(abandoned.id, status="done")
        store.archive(abandoned.id)
        assert outstanding.id  # still live, still owed

        from projectman.hub.rollup import rollup

        data = rollup(tmp_hub)
        assert data["total_points"] == 8
        assert data["completed_points"] == 5
        assert data["completion"] == "62%"
        assert data["projects"][0]["total_points"] == 8
        assert data["projects"][0]["completed_points"] == 5

    def test_rollup_still_counts_genuinely_delivered_work(self, tmp_hub):
        store = self._subproject_store(tmp_hub)
        story, _ = store.create_story("Story", "Desc")
        for title, points in (("A", 5), ("B", 3)):
            task = store.create_task(story.id, title, "D" * 40, points=points)
            store.update(task.id, status="done")

        from projectman.hub.rollup import rollup

        data = rollup(tmp_hub)
        assert data["total_points"] == 8
        assert data["completed_points"] == 8
        assert data["completion"] == "100%"

    def test_hub_burndown_dashboard_reports_delivered_work_only(self, tmp_hub):
        store = self._subproject_store(tmp_hub)
        story, _ = store.create_story("Story", "Desc")
        delivered = store.create_task(story.id, "Delivered", "D" * 40, points=5)
        abandoned = store.create_task(story.id, "Abandoned", "D" * 40, points=8)
        store.update(delivered.id, status="done")
        store.update(abandoned.id, status="done")
        store.archive(abandoned.id)

        from projectman.hub.dashboards import generate_dashboards

        generate_dashboards(tmp_hub)
        text = (tmp_hub / ".project" / "dashboards" / "burndown.md").read_text()
        assert "**Total Points:** 5" in text
        assert "**Completed:** 5" in text
        assert "**Remaining:** 0" in text


# ─── Archived epics ──────────────────────────────────────────────


class TestArchivedEpicsLeaveTheRollup:
    """Epics are excluded by a *different* mechanism to tasks: they carry
    ``archived`` as a status value and ``list_epics`` drops them before
    ``build_index`` is called.  Pinned so a refactor that consolidates the
    listing accessors cannot quietly readmit them."""

    def test_an_archived_epic_leaves_the_index_counts(self, store):
        epic = store.create_epic("Epic", "Desc")
        assert build_index(store).epic_count == 1

        store.archive(epic.id)
        index = build_index(store)
        assert index.epic_count == 0
        assert not [e for e in index.entries if e.type == "epic"]

    def test_a_live_epic_is_still_counted(self, store):
        store.create_epic("Epic", "Desc")
        assert build_index(store).epic_count == 1

    def test_archiving_an_epic_does_not_write_off_its_live_stories(self, store):
        """Only the archived item leaves the math.  Stories under a shelved
        epic are still real work until they are archived themselves —
        dropping them silently would understate what the project owes."""
        epic = store.create_epic("Epic", "Desc")
        story, _ = store.create_story("Story", "Desc", points=5)
        store.update(story.id, epic_id=epic.id)
        store.archive(epic.id)

        index = build_index(store)
        assert index.epic_count == 0
        assert index.total_points == 5
        assert index.completed_points == 0
