"""Removal policy for orphaned test tasks.

US-PM-5-6.  When a criterion is deleted, its auto-generated test task becomes
an orphan.  The policy:

* nothing has happened to the task  -> archive it (US-PM-16 archival: the
  ``archived`` flag flips, status/title/body are preserved, ``Store.unarchive``
  undoes it).  Never delete.
* anything has happened to the task -> leave it byte-for-byte alone and flag
  it, with machine-readable reason codes, for a human.

These tests pin both branches, every boundary of "untouched", and the fact
that the policy never removes a file from disk.
"""

import hashlib

import pytest

from projectman.store import (
    ORPHAN_ACTION_ARCHIVE,
    ORPHAN_ACTION_FLAG,
    Store,
    clear_all_caches,
    generate_test_task_body,
)


def _orphans(store):
    return store.last_criteria_reconciliation["orphaned"]


def _only_orphan(store):
    orphans = _orphans(store)
    assert len(orphans) == 1, orphans
    return orphans[0]


def _two_criteria_story(store):
    """A story with criteria Alpha/Beta; ``-2`` is about to be orphaned."""
    meta, _ = store.create_story(
        "S", "body text here", acceptance_criteria=["Alpha criterion", "Beta criterion"]
    )
    return meta.id


def _drop_beta(store, story_id):
    store.update(story_id, acceptance_criteria=["Alpha criterion"])


def _task_digest(store, task_id):
    """Fingerprint of a task file's bytes."""
    path = store._task_path(task_id)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestUntouchedOrphanIsArchivedNotDeleted:
    def test_the_file_still_exists(self, store):
        sid = _two_criteria_story(store)
        _drop_beta(store, sid)
        assert store._task_path(f"{sid}-2").exists()

    def test_it_is_archived(self, store):
        sid = _two_criteria_story(store)
        _drop_beta(store, sid)
        meta, _ = store.get_task(f"{sid}-2")
        assert meta.archived is True

    def test_status_title_and_body_are_preserved(self, store):
        sid = _two_criteria_story(store)
        before_meta, before_body = store.get_task(f"{sid}-2")
        _drop_beta(store, sid)
        after_meta, after_body = store.get_task(f"{sid}-2")
        assert after_meta.status == before_meta.status
        assert after_meta.title == before_meta.title
        assert after_body == before_body
        # The criterion text the story dropped survives in the task body.
        assert after_body == generate_test_task_body(sid, "Beta criterion")

    def test_the_verdict_is_reported(self, store):
        sid = _two_criteria_story(store)
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_ARCHIVE
        assert orphan["work_reasons"] == []
        assert orphan["has_work"] is False
        assert orphan["archived"] is True
        assert store.last_criteria_reconciliation["archived_task_ids"] == [f"{sid}-2"]
        assert store.last_criteria_reconciliation["flagged_task_ids"] == []

    def test_archiving_survives_a_fresh_store(self, store, tmp_project):
        sid = _two_criteria_story(store)
        _drop_beta(store, sid)
        clear_all_caches()
        fresh = Store(tmp_project)
        meta, _ = fresh.get_task(f"{sid}-2")
        assert meta.archived is True
        # And it drops out of the active working set.
        assert f"{sid}-2" not in [
            t.id for t in fresh.list_tasks(story_id=sid, archived=False)
        ]

    def test_archiving_is_reversible(self, store):
        sid = _two_criteria_story(store)
        _drop_beta(store, sid)
        store.unarchive(f"{sid}-2")
        meta, body = store.get_task(f"{sid}-2")
        assert meta.archived is False
        assert body == generate_test_task_body(sid, "Beta criterion")


class TestWorkStartedMeansFlagNotArchive:
    """Each boundary of "untouched", tested one signal at a time."""

    @pytest.mark.parametrize(
        "status,code",
        [
            ("in-progress", "status-not-todo"),
            ("review", "status-not-todo"),
            ("blocked", "status-not-todo"),
            ("done", "status-not-todo"),
        ],
    )
    def test_status_moved_off_todo(self, store, status, code):
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", status=status)
        digest = _task_digest(store, f"{sid}-2")
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert code in orphan["work_reasons"]
        assert _task_digest(store, f"{sid}-2") == digest

    def test_assignee_set(self, store):
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", assignee="ryan")
        digest = _task_digest(store, f"{sid}-2")
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["assigned"]
        assert _task_digest(store, f"{sid}-2") == digest

    def test_run_log_entry_alone_is_enough(self, store):
        """The subtle one: still todo, still unassigned, but attempted."""
        sid = _two_criteria_story(store)
        store._append_run_log(f"{sid}-2", outcome="failed", note="tried, could not")
        digest = _task_digest(store, f"{sid}-2")
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["status"] == "todo"
        assert orphan["assignee"] is None
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["run-log-entries"]
        assert _task_digest(store, f"{sid}-2") == digest

    def test_info_only_run_log_entry_still_counts(self, store):
        sid = _two_criteria_story(store)
        store._append_run_log(f"{sid}-2", outcome="info", note="looked at it")
        _drop_beta(store, sid)
        assert _only_orphan(store)["action"] == ORPHAN_ACTION_FLAG

    def test_human_renamed_title(self, store):
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", title="Check the beta path by hand")
        digest = _task_digest(store, f"{sid}-2")
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["title-edited"]
        assert _task_digest(store, f"{sid}-2") == digest

    def test_task_depends_on_something(self, store):
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", depends_on=[f"{sid}-1"])
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["has-dependencies"]

    def test_something_depends_on_the_task(self, store):
        sid = _two_criteria_story(store)
        impl = store.create_task(sid, "Implement beta", "Write the beta path")
        store.update(impl.id, depends_on=[f"{sid}-2"])
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["has-dependents"]

    def test_several_signals_are_all_reported(self, store):
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        store._append_run_log(f"{sid}-2", outcome="partial", note="halfway")
        _drop_beta(store, sid)
        orphan = _only_orphan(store)
        assert orphan["work_reasons"] == [
            "status-not-todo",
            "assigned",
            "run-log-entries",
        ]
        assert store.last_criteria_reconciliation["flagged_task_ids"] == [f"{sid}-2"]
        assert store.last_criteria_reconciliation["archived_task_ids"] == []

    def test_flagged_task_is_still_in_the_active_working_set(self, store, tmp_project):
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", assignee="ryan")
        _drop_beta(store, sid)
        clear_all_caches()
        fresh = Store(tmp_project)
        assert f"{sid}-2" in [
            t.id for t in fresh.list_tasks(story_id=sid, archived=False)
        ]


class TestOutOfScopeTasksAreUntouchable:
    def test_a_human_rewritten_body_is_not_an_orphan_at_all(self, store):
        """Not parseable as auto-generated -> invisible to the whole policy."""
        sid = _two_criteria_story(store)
        store.update(f"{sid}-2", body="I rewrote this by hand and own it now")
        digest = _task_digest(store, f"{sid}-2")
        _drop_beta(store, sid)
        assert _orphans(store) == []
        meta, _ = store.get_task(f"{sid}-2")
        assert meta.archived is False
        assert _task_digest(store, f"{sid}-2") == digest

    def test_an_already_archived_orphan_is_left_alone(self, store):
        sid = _two_criteria_story(store)
        store.archive(f"{sid}-2")
        digest = _task_digest(store, f"{sid}-2")
        _drop_beta(store, sid)
        assert _orphans(store) == []
        assert _task_digest(store, f"{sid}-2") == digest

    def test_a_manual_task_is_never_archived(self, store):
        sid = _two_criteria_story(store)
        manual = store.create_task(sid, "Implement the beta path", "Do the work")
        digest = _task_digest(store, manual.id)
        _drop_beta(store, sid)
        meta, _ = store.get_task(manual.id)
        assert meta.archived is False
        assert _task_digest(store, manual.id) == digest

    def test_a_matched_task_is_never_archived(self, store):
        """Only orphans are in scope — surviving criteria keep active tasks."""
        sid = _two_criteria_story(store)
        _drop_beta(store, sid)
        meta, _ = store.get_task(f"{sid}-1")
        assert meta.archived is False


class TestNothingIsEverDeleted:
    def test_task_count_on_disk_never_drops(self, store, tmp_project):
        sid = _two_criteria_story(store)
        tasks_dir = tmp_project / ".project" / "tasks"
        before = sorted(p.name for p in tasks_dir.glob("*.md"))
        store.update(sid, acceptance_criteria=["Totally unrelated replacement text"])
        after = sorted(p.name for p in tasks_dir.glob("*.md"))
        assert set(before).issubset(set(after))
        assert len(after) == len(before) + 1  # the replacement criterion's task

    def test_a_below_threshold_rewording_archives_rather_than_destroys(self, store):
        """The matcher's known failure mode must not become data loss."""
        sid = _two_criteria_story(store)
        store.update(
            sid, acceptance_criteria=["Alpha criterion", "Wholly unrelated wording"]
        )
        orphan = _only_orphan(store)
        assert orphan["action"] == ORPHAN_ACTION_ARCHIVE
        _, body = store.get_task(f"{sid}-2")
        assert "Beta criterion" in body

    def test_dropping_every_criterion_archives_every_test_task(self, store):
        sid = _two_criteria_story(store)
        store.update(sid, acceptance_criteria=[])
        # An empty list is falsy, so update() skips the frontmatter write but
        # not the reconciliation; either way nothing may be deleted.
        for n in (1, 2):
            assert store._task_path(f"{sid}-{n}").exists()


class TestPlanRemainsPure:
    def test_planning_archives_nothing(self, store):
        sid = _two_criteria_story(store)
        plan = store.plan_criteria_reconciliation(sid, ["Alpha criterion"])
        assert plan["orphaned"][0]["action"] == ORPHAN_ACTION_ARCHIVE
        meta, _ = store.get_task(f"{sid}-2")
        assert meta.archived is False


class TestMcpSurface:
    """Requirement 3: an automated caller must learn what happened."""

    @staticmethod
    def _setup(tmp_project, monkeypatch):
        from projectman import server

        monkeypatch.chdir(tmp_project)
        server._store_cache.clear()
        clear_all_caches()
        return server

    def test_archived_branch_is_visible_in_the_response(
        self, tmp_project, monkeypatch
    ):
        import yaml

        server = self._setup(tmp_project, monkeypatch)
        server.pm_create_story("S", "body text", acceptance_criteria=["Alpha", "Beta"])
        out = yaml.safe_load(server.pm_update("US-TST-1", acceptance_criteria=["Alpha"]))
        tt = out["test_tasks"]
        assert tt["archived"] == ["US-TST-1-2"]
        assert tt["flagged"] == []
        assert tt["needs_attention"] is False
        assert tt["orphaned"][0]["action"] == "archive"
        assert tt["orphaned"][0]["work_reasons"] == []

    def test_flagged_branch_is_visible_in_the_response(self, tmp_project, monkeypatch):
        import yaml

        server = self._setup(tmp_project, monkeypatch)
        server.pm_create_story("S", "body text", acceptance_criteria=["Alpha", "Beta"])
        server.pm_update("US-TST-1-2", status="in-progress", assignee="ryan")
        out = yaml.safe_load(server.pm_update("US-TST-1", acceptance_criteria=["Alpha"]))
        tt = out["test_tasks"]
        assert tt["archived"] == []
        assert tt["flagged"] == ["US-TST-1-2"]
        assert tt["needs_attention"] is True
        orphan = tt["orphaned"][0]
        assert orphan["action"] == "flag"
        assert orphan["work_reasons"] == ["status-not-todo", "assigned"]

    def test_a_caller_can_branch_without_string_matching(
        self, tmp_project, monkeypatch
    ):
        import yaml

        server = self._setup(tmp_project, monkeypatch)
        server.pm_create_story("S", "body text", acceptance_criteria=["Alpha", "Beta", "Gamma"])
        server.pm_update("US-TST-1-3", assignee="ryan")
        out = yaml.safe_load(server.pm_update("US-TST-1", acceptance_criteria=["Alpha"]))
        tt = out["test_tasks"]
        # archived and flagged partition orphaned, no overlap, no remainder.
        assert set(tt["archived"]) == {"US-TST-1-2"}
        assert set(tt["flagged"]) == {"US-TST-1-3"}
        assert set(tt["archived"]) | set(tt["flagged"]) == {
            o["id"] for o in tt["orphaned"]
        }
        assert not set(tt["archived"]) & set(tt["flagged"])
        assert all(
            o["action"] in ("archive", "flag") and isinstance(o["work_reasons"], list)
            for o in tt["orphaned"]
        )

    def test_the_archived_task_is_still_on_disk_after_the_server_call(
        self, tmp_project, monkeypatch
    ):
        server = self._setup(tmp_project, monkeypatch)
        server.pm_create_story("S", "body text", acceptance_criteria=["Alpha", "Beta"])
        server.pm_update("US-TST-1", acceptance_criteria=["Alpha"])
        clear_all_caches()
        store = Store(tmp_project)
        meta, body = store.get_task("US-TST-1-2")
        assert meta.archived is True
        assert "Beta" in body
        # ...and Store.unarchive puts it straight back.
        store.unarchive("US-TST-1-2")
        assert store.get_task("US-TST-1-2")[0].archived is False
