"""Reconciliation of auto-generated test tasks when acceptance criteria change.

US-PM-5-5.  ``Store.create_story`` generated one test task per acceptance
criterion but ``Store.update`` never reconciled them, so editing a story's
criteria left tasks quoting criteria that no longer existed and created
nothing for the new ones.
"""

import hashlib

import pytest

from projectman.store import (
    ORPHAN_ACTION_ARCHIVE,
    ORPHAN_ACTION_FLAG,
    criterion_from_test_task_body,
    criterion_similarity,
    generate_test_task_body,
    generate_test_task_title,
)


def _tasks(store, story_id):
    """Return {task_id: (title, body)} for every task under a story."""
    out = {}
    for meta in store.list_tasks(story_id=story_id):
        _, body = store.get_task(meta.id)
        out[meta.id] = (meta.title, body)
    return out


def _test_task_criteria(store, story_id):
    """Criterion text each auto-generated test task currently quotes, in id order."""
    pairs = store._test_tasks_for_story(story_id)
    return [criterion for _meta, criterion in pairs]


def _tree_digest(root, exclude=("activity.jsonl",)):
    """Byte-level fingerprint of every file under *root*.

    ``activity.jsonl`` is excluded by default: ``Store.update`` appends one
    ``update`` event for the item being updated on *every* call, reconciliation
    or not.  That is pre-existing behaviour and unrelated to this story, so the
    idempotency tests below pair this digest with an explicit assertion about
    what the activity log did gain.
    """
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = str(path.relative_to(root))
        if rel in exclude:
            continue
        h.update(rel.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def _activity_ids(tmp_project):
    """Item ids recorded in the activity log, in order."""
    import json

    log = tmp_project / ".project" / "activity.jsonl"
    if not log.exists():
        return []
    return [
        json.loads(line)["item_id"] for line in log.read_text().splitlines() if line.strip()
    ]


class TestGenerationHelpersAreShared:
    """create_story and update must go through one generator, not two copies."""

    def test_create_story_uses_the_shared_generator(self, store):
        criteria = ["Users can log in", "Errors are shown"]
        meta, tasks = store.create_story("S", "body", acceptance_criteria=criteria)
        for task, criterion in zip(tasks, criteria):
            _, body = store.get_task(task.id)
            assert task.title == generate_test_task_title(criterion)
            assert body == generate_test_task_body(meta.id, criterion)

    def test_body_generator_and_parser_round_trip(self):
        criterion = "A criterion with > angle brackets, commas and 'quotes'"
        body = generate_test_task_body("US-TST-1", criterion)
        assert criterion_from_test_task_body("US-TST-1", body) == criterion

    def test_parser_rejects_a_hand_written_body(self):
        assert criterion_from_test_task_body("US-TST-1", "Just some notes") is None

    def test_parser_rejects_another_storys_body(self):
        body = generate_test_task_body("US-TST-2", "something")
        assert criterion_from_test_task_body("US-TST-1", body) is None

    def test_titles_are_truncated_at_120_chars(self):
        criterion = "x" * 400
        title = generate_test_task_title(criterion)
        assert len(title) == 120
        assert title.endswith("...")


class TestAddingCriteria:
    def test_new_criterion_gets_a_test_task(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A", "B"])
        store.update(meta.id, acceptance_criteria=["A", "B", "C"])
        assert _test_task_criteria(store, meta.id) == ["A", "B", "C"]

    def test_new_task_matches_create_story_generation_exactly(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A"])
        store.update(meta.id, acceptance_criteria=["A", "Brand new criterion"])
        tasks = _tasks(store, meta.id)
        new_id = f"{meta.id}-2"
        assert tasks[new_id] == (
            generate_test_task_title("Brand new criterion"),
            generate_test_task_body(meta.id, "Brand new criterion"),
        )

    def test_long_new_criterion_is_truncated_the_same_way(self, store):
        long_criterion = "L" * 300
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A"])
        store.update(meta.id, acceptance_criteria=["A", long_criterion])
        task_meta, _ = store.get_task(f"{meta.id}-2")
        assert task_meta.title == generate_test_task_title(long_criterion)
        assert len(task_meta.title) == 120
        # The full untruncated criterion still lives in the body.
        _, body = store.get_task(f"{meta.id}-2")
        assert body == generate_test_task_body(meta.id, long_criterion)

    def test_criteria_added_to_a_story_that_had_none(self, store):
        meta, tasks = store.create_story("S", "b")
        assert tasks == []
        store.update(meta.id, acceptance_criteria=["First criterion"])
        assert _test_task_criteria(store, meta.id) == ["First criterion"]

    def test_reconciliation_result_is_exposed(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A"])
        store.update(meta.id, acceptance_criteria=["A", "B"])
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-2"]
        assert [e["criterion"] for e in result["unchanged"]] == ["A"]
        assert result["resync"] == []
        assert result["orphaned"] == []


class TestEditingCriteria:
    def test_edited_criterion_syncs_title_and_body(self, store):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Users can log in with a password"]
        )
        edited = "Users can log in with a password or a passkey"
        store.update(meta.id, acceptance_criteria=[edited])
        task_meta, body = store.get_task(f"{meta.id}-1")
        assert task_meta.title == generate_test_task_title(edited)
        assert body == generate_test_task_body(meta.id, edited)

    def test_edit_reuses_the_task_rather_than_creating_one(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        store.update(meta.id, acceptance_criteria=["Alpha criterion revised"])
        assert len(store.list_tasks(story_id=meta.id)) == 1
        assert store.last_criteria_reconciliation["created_task_ids"] == []
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-1"
        ]

    def test_only_the_edited_criterion_task_is_rewritten(self, store):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        before = _tasks(store, meta.id)
        store.update(
            meta.id, acceptance_criteria=["Alpha criterion", "Beta criterion edited"]
        )
        after = _tasks(store, meta.id)
        assert after[f"{meta.id}-1"] == before[f"{meta.id}-1"]
        assert after[f"{meta.id}-2"] != before[f"{meta.id}-2"]

    def test_wholesale_rewrite_reads_as_remove_plus_add(self, store):
        """Honest failure mode: past the similarity threshold it is a new criterion."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        store.update(meta.id, acceptance_criteria=["Completely unrelated wording here"])
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-2"]
        assert [e["task_id"] for e in result["orphaned"]] == [f"{meta.id}-1"]


class TestReorderingAndInserting:
    def test_reordering_creates_and_modifies_nothing(self, store, tmp_project):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one", "B two", "C three"])
        before = _tree_digest(tmp_project / ".project" / "tasks")
        store.update(meta.id, acceptance_criteria=["C three", "B two", "A one"])
        assert _tree_digest(tmp_project / ".project" / "tasks") == before
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == []
        assert result["resync"] == []
        assert result["orphaned"] == []

    def test_inserting_in_the_middle_only_adds_one_task(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one", "C three"])
        before = _tasks(store, meta.id)
        store.update(meta.id, acceptance_criteria=["A one", "B two", "C three"])
        after = _tasks(store, meta.id)
        # The two originals are untouched — no positional smearing.
        assert after[f"{meta.id}-1"] == before[f"{meta.id}-1"]
        assert after[f"{meta.id}-2"] == before[f"{meta.id}-2"]
        assert after[f"{meta.id}-3"] == (
            generate_test_task_title("B two"),
            generate_test_task_body(meta.id, "B two"),
        )

    def test_insert_then_edit_the_inserted_criterion(self, store):
        """The task added mid-list is still matched later despite its id order."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one", "C three"])
        store.update(meta.id, acceptance_criteria=["A one", "B two", "C three"])
        store.update(
            meta.id, acceptance_criteria=["A one", "B two edited", "C three"]
        )
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-3"
        ]
        assert sorted(_test_task_criteria(store, meta.id)) == [
            "A one",
            "B two edited",
            "C three",
        ]

    def test_reorder_and_add_together(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one", "B two"])
        store.update(meta.id, acceptance_criteria=["B two", "New third", "A one"])
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-3"]
        assert result["resync"] == []


class TestIdempotency:
    def test_unchanged_criteria_change_nothing_on_disk(self, store, tmp_project):
        criteria = ["Users can log in", "Errors are shown", "Sessions expire"]
        meta, _ = store.create_story("S", "b", acceptance_criteria=criteria)
        project = tmp_project / ".project"
        before = _tree_digest(project)
        activity_before = _activity_ids(tmp_project)
        store.update(meta.id, acceptance_criteria=list(criteria))
        assert _tree_digest(project) == before
        assert store.last_criteria_reconciliation is None
        # The only new activity is the story update itself — no task events.
        assert _activity_ids(tmp_project) == activity_before + [meta.id]

    def test_repeated_identical_updates_are_stable(self, store, tmp_project):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one", "B two"])
        store.update(meta.id, acceptance_criteria=["A one", "B two", "C three"])
        project = tmp_project / ".project"
        after_first = _tree_digest(project)
        for _ in range(3):
            store.update(meta.id, acceptance_criteria=["A one", "B two", "C three"])
        assert _tree_digest(project) == after_first

    def test_non_criteria_update_does_not_reconcile(self, store, tmp_project):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one", "B two"])
        tasks_dir = tmp_project / ".project" / "tasks"
        before = _tree_digest(tasks_dir)
        store.update(meta.id, status="ready", points=3, title="Renamed")
        assert _tree_digest(tasks_dir) == before
        assert store.last_criteria_reconciliation is None

    def test_body_only_update_does_not_reconcile(self, store, tmp_project):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["A one"])
        tasks_dir = tmp_project / ".project" / "tasks"
        before = _tree_digest(tasks_dir)
        store.update(meta.id, body="A rewritten story body")
        assert _tree_digest(tasks_dir) == before

    def test_story_with_no_criteria_is_unaffected(self, store, tmp_project):
        meta, _ = store.create_story("S", "b")
        project = tmp_project / ".project"
        store.update(meta.id, status="ready")
        assert store.list_tasks(story_id=meta.id) == []
        assert store.last_criteria_reconciliation is None
        before = _tree_digest(project)
        store.update(meta.id, acceptance_criteria=[])
        assert _tree_digest(project) == before


class TestRemovalIsNotOurJob:
    """US-PM-5-6 owns the removal policy; 5-5 must only report, never destroy.

    Since 5-6 landed, an untouched orphan is archived rather than left alone —
    but the file, its title, its body and its status are still exactly what
    they were, which is what these tests actually guard.
    """

    def test_removed_criterion_task_survives_untouched(self, store):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        before = _tasks(store, meta.id)
        store.update(meta.id, acceptance_criteria=["Alpha criterion"])
        after = _tasks(store, meta.id)
        # Title and body are untouched — only the archived flag moved.
        assert after[f"{meta.id}-2"] == before[f"{meta.id}-2"]
        task_meta, _ = store.get_task(f"{meta.id}-2")
        assert task_meta.status.value == "todo"

    def test_orphans_are_reported_with_work_state(self, store):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        store.update(f"{meta.id}-2", status="in-progress", assignee="ryan")
        store.update(meta.id, acceptance_criteria=["Alpha criterion"])
        orphans = store.last_criteria_reconciliation["orphaned"]
        assert len(orphans) == 1
        assert orphans[0]["task_id"] == f"{meta.id}-2"
        assert orphans[0]["criterion"] == "Beta criterion"
        assert orphans[0]["status"] == "in-progress"
        assert orphans[0]["assignee"] == "ryan"
        assert orphans[0]["has_work"] is True

    def test_untouched_orphan_reports_no_work(self, store):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        store.update(meta.id, acceptance_criteria=["Alpha criterion"])
        orphans = store.last_criteria_reconciliation["orphaned"]
        assert orphans[0]["has_work"] is False

    def test_plan_is_read_only(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        project = tmp_project / ".project"
        before = _tree_digest(project)
        plan = store.plan_criteria_reconciliation(meta.id, ["Alpha criterion", "New"])
        assert _tree_digest(project) == before
        assert [e["criterion"] for e in plan["create"]] == ["New"]
        assert [e["task_id"] for e in plan["orphaned"]] == [f"{meta.id}-2"]


class TestManualAndHumanEditedTasks:
    def test_manual_tasks_are_never_touched(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        manual = store.create_task(meta.id, "Implement the login form", "Do the work")
        before = _tasks(store, meta.id)[manual.id]
        store.update(
            meta.id, acceptance_criteria=["Alpha criterion revised", "Brand new one"]
        )
        assert _tasks(store, meta.id)[manual.id] == before
        assert manual.id not in [
            e["task_id"] for e in store.last_criteria_reconciliation["orphaned"]
        ]

    def test_manual_task_titled_like_a_test_task_is_ignored(self, store):
        """Identification is by generated body, not by the 'Test: ' title prefix."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        manual = store.create_task(
            meta.id, "Test: something a human wrote", "My own notes"
        )
        before = _tasks(store, meta.id)[manual.id]
        store.update(meta.id, acceptance_criteria=["Alpha criterion revised"])
        assert _tasks(store, meta.id)[manual.id] == before

    def test_human_rewritten_body_drops_out_of_scope(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        store.update(f"{meta.id}-1", body="I rewrote this test plan by hand")
        before = _tasks(store, meta.id)[f"{meta.id}-1"]
        store.update(meta.id, acceptance_criteria=["Alpha criterion revised"])
        # Left exactly as the human wrote it; a fresh task covers the criterion.
        assert _tasks(store, meta.id)[f"{meta.id}-1"] == before
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-2"
        ]

    def test_human_renamed_title_is_preserved_but_body_resyncs(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        store.update(f"{meta.id}-1", title="Login smoke test")
        store.update(meta.id, acceptance_criteria=["Alpha criterion revised"])
        task_meta, body = store.get_task(f"{meta.id}-1")
        assert task_meta.title == "Login smoke test"
        assert body == generate_test_task_body(meta.id, "Alpha criterion revised")
        assert store.last_criteria_reconciliation["resync"][0]["retitle"] is False

    def test_archived_test_task_is_not_resurrected(self, store):
        """US-PM-1-1/US-PM-2-1 were archived as obsolete — do not rewrite them."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha criterion"])
        store.archive(f"{meta.id}-1")
        before = _tasks(store, meta.id)[f"{meta.id}-1"]
        store.update(meta.id, acceptance_criteria=["Alpha criterion revised"])
        assert _tasks(store, meta.id)[f"{meta.id}-1"] == before
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-2"
        ]


class TestLegacyTasksWithoutStoredReference:
    """Every task in every real project predates this change."""

    def test_legacy_story_created_before_reconciliation_still_matches(
        self, store, tmp_project
    ):
        """Simulate a pre-0.8.9 project: task files carry no new frontmatter."""
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        raw = (tmp_project / ".project" / "tasks" / f"{meta.id}-1.md").read_text()
        # No reconciliation-specific frontmatter key was ever written.
        assert "criterion:" not in raw.split("---")[1]
        store.update(
            meta.id, acceptance_criteria=["Alpha criterion edited", "Beta criterion"]
        )
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-1"
        ]

    def test_matching_survives_double_digit_task_numbers(self, store):
        criteria = [f"Criterion number {i}" for i in range(1, 13)]
        meta, _ = store.create_story("S", "b", acceptance_criteria=criteria)
        edited = list(criteria)
        edited[11] = "Criterion number 12 edited"
        store.update(meta.id, acceptance_criteria=edited)
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-12"
        ]


class TestReproductionOfTheOriginalBug:
    def test_original_reported_reproduction(self, store):
        """Create with criteria, edit them: no stale quotes, no missing tasks."""
        meta, _ = store.create_story(
            "S",
            "b",
            acceptance_criteria=[
                "Oversized notes are truncated server-side",
                "Response carries a note_truncated flag",
            ],
        )
        new_criteria = [
            "Oversized notes are truncated server-side with a visible marker",
            "Response carries a note_truncated flag so the caller knows",
            "The status and outcome portion of the write always lands",
        ]
        store.update(meta.id, acceptance_criteria=new_criteria)

        live = _test_task_criteria(store, meta.id)
        # Every criterion has a task...
        for criterion in new_criteria:
            assert criterion in live
        # ...and no active test task quotes a criterion that no longer exists.
        assert set(live) <= set(new_criteria)


class TestMcpLayer:
    def test_pm_update_reconciles_through_the_server(self, tmp_project, monkeypatch):
        from projectman import server
        from projectman.store import Store, clear_all_caches

        monkeypatch.chdir(tmp_project)
        server._store_cache.clear()
        clear_all_caches()

        server.pm_create_story("S", "b", acceptance_criteria="Alpha criterion")
        server.pm_update("US-TST-1", acceptance_criteria="Alpha criterion,Beta criterion")

        clear_all_caches()
        fresh = Store(tmp_project)
        assert sorted(_test_task_criteria(fresh, "US-TST-1")) == [
            "Alpha criterion",
            "Beta criterion",
        ]

    def test_pm_update_reports_created_and_orphaned_tasks(self, tmp_project, monkeypatch):
        import yaml

        from projectman import server
        from projectman.store import clear_all_caches

        monkeypatch.chdir(tmp_project)
        server._store_cache.clear()
        clear_all_caches()

        server.pm_create_story(
            "S", "b", acceptance_criteria="Alpha criterion,Beta criterion"
        )
        out = yaml.safe_load(
            server.pm_update("US-TST-1", acceptance_criteria="Alpha criterion,Gamma one")
        )
        assert out["test_tasks"]["created"] == ["US-TST-1-3"]
        assert out["test_tasks"]["orphaned"][0]["id"] == "US-TST-1-2"
        assert out["test_tasks"]["orphaned"][0]["criterion"] == "Beta criterion"
        assert out["test_tasks"]["orphaned"][0]["has_work"] is False

    def test_pm_update_omits_test_tasks_when_nothing_moved(self, tmp_project, monkeypatch):
        import yaml

        from projectman import server
        from projectman.store import clear_all_caches

        monkeypatch.chdir(tmp_project)
        server._store_cache.clear()
        clear_all_caches()

        server.pm_create_story("S", "b", acceptance_criteria="Alpha criterion")
        out = yaml.safe_load(server.pm_update("US-TST-1", status="ready"))
        assert "test_tasks" not in out
        out = yaml.safe_load(
            server.pm_update("US-TST-1", acceptance_criteria="Alpha criterion")
        )
        assert "test_tasks" not in out


@pytest.mark.parametrize(
    "old,new,expect_resync",
    [
        (["Sessions expire after 30 minutes"], ["Sessions expire after 60 minutes"], True),
        (["Sessions expire after 30 minutes"], ["Sessions expire after 30 minutes."], True),
        (["Alpha"], ["Totally different text entirely"], False),
    ],
)
def test_similarity_threshold_behaviour(store, old, new, expect_resync):
    meta, _ = store.create_story("S", "b", acceptance_criteria=old)
    plan = store.plan_criteria_reconciliation(meta.id, new)
    assert bool(plan["resync"]) is expect_resync
    assert bool(plan["create"]) is not expect_resync


# =======================================================================
# US-PM-5-3 — "Test task title and body stay in sync with the criterion
# text."  The classes above prove reconciliation *moves* the right tasks;
# these prove the criterion itself: that after any edit, the surviving
# task's parsed title and parsed body are exactly what the generators
# produce for the criterion now in the story — for real criterion text,
# not just for short ASCII identifiers, and on disk rather than only in
# the in-process cache.
# =======================================================================


SEED = "Alpha criterion"

# Each of these is an edit of SEED (they all contain it, so the
# similarity matcher pairs them with the seed's task rather than
# treating them as a brand-new criterion).  The point is the *text*:
# every one of them is hostile to some layer the criterion has to
# survive — YAML frontmatter, markdown blockquotes, the title
# truncator, or the body parser.
REAL_WORLD_CRITERION_TEXTS = [
    pytest.param(f"{SEED} about logging in and out", id="ascii"),
    pytest.param(f"{SEED} — with café ☕, naïve and 日本語", id="unicode"),
    pytest.param(f'{SEED}: after 30 min, "hard", 100%! (no grace)', id="punctuation"),
    pytest.param(f"{SEED}: value", id="leading-key-colon"),
    pytest.param(f"> {SEED} already blockquoted", id="blockquote-marker"),
    pytest.param(f"{SEED}\nwith a second line", id="multiline"),
    pytest.param(f"{SEED}\n---\nnot frontmatter", id="yaml-delimiter"),
    pytest.param(f"{SEED} with an apostrophe's tail", id="apostrophe"),
    pytest.param(f"{SEED} with a literal \\n backslash-n", id="backslash-n"),
    pytest.param(f"{SEED} #hash and *stars* and `ticks`", id="markdown"),
    pytest.param(f"{SEED} " + "x" * 300, id="very-long"),
]


def _fresh_store(tmp_project):
    """A Store that has to read every byte back off disk.

    Every other helper in this file reads through the module-level cache,
    which ``_write_test_task_sync`` updates in the same breath as it
    writes the file.  A resync that lands in the cache but not on disk —
    or that the serialiser mangles on the way out — is invisible to those
    reads and visible to this one.
    """
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


def _assert_in_sync(store, story_id, task_id, criterion):
    """The task's parsed title and parsed body are the generated pair."""
    meta, body = store.get_task(task_id)
    assert meta.title == generate_test_task_title(criterion)
    assert body == generate_test_task_body(story_id, criterion)
    # ...and the association is recoverable, which is what makes the next
    # edit find this task instead of orphaning it.
    assert criterion_from_test_task_body(story_id, body) == criterion


class TestTitleAndBodySyncWithCriterionText:
    @pytest.mark.parametrize("edited", REAL_WORLD_CRITERION_TEXTS)
    def test_edit_syncs_both_title_and_body(self, store, edited):
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        store.update(meta.id, acceptance_criteria=[edited])
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-1"
        ]
        _assert_in_sync(store, meta.id, f"{meta.id}-1", edited)

    @pytest.mark.parametrize("edited", REAL_WORLD_CRITERION_TEXTS)
    def test_sync_survives_the_round_trip_to_disk(self, store, tmp_project, edited):
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        store.update(meta.id, acceptance_criteria=[edited])
        _assert_in_sync(_fresh_store(tmp_project), meta.id, f"{meta.id}-1", edited)

    @pytest.mark.parametrize("criterion", REAL_WORLD_CRITERION_TEXTS)
    def test_creation_path_also_survives_the_round_trip(
        self, store, tmp_project, criterion
    ):
        """The two paths must agree, so hold create_story to the same bar."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=[criterion])
        _assert_in_sync(_fresh_store(tmp_project), meta.id, f"{meta.id}-1", criterion)

    def test_successive_edits_each_resync_to_the_latest_text(self, store, tmp_project):
        """Sync is not a one-shot property — it has to hold after every edit."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        history = [
            f"{SEED} about login",
            f"{SEED} about login and logout",
            f"{SEED} about login, logout and session expiry",
            f"{SEED} about login, logout and session expiry (30 min)",
        ]
        for criterion in history:
            store.update(meta.id, acceptance_criteria=[criterion])
            _assert_in_sync(store, meta.id, f"{meta.id}-1", criterion)
        # Still one task: every edit re-used it rather than accumulating.
        assert len(store.list_tasks(story_id=meta.id, archived=None)) == 1
        _assert_in_sync(_fresh_store(tmp_project), meta.id, f"{meta.id}-1", history[-1])

    def test_resync_truncates_the_title_but_keeps_the_whole_body(self, store):
        """Title sync means "the generated title", which is a truncation."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        long_criterion = f"{SEED} " + "y" * 300
        store.update(meta.id, acceptance_criteria=[long_criterion])
        task_meta, body = store.get_task(f"{meta.id}-1")
        assert len(task_meta.title) == 120
        assert task_meta.title.endswith("...")
        # The body is the lossless record — the full 316 characters.
        assert criterion_from_test_task_body(meta.id, body) == long_criterion

    def test_trimming_a_long_criterion_untruncates_the_title(self, store):
        """The reverse direction: a title that was truncated must come back.

        The trim has to stay inside ``CRITERION_EDIT_SIMILARITY`` to count
        as an edit at all — a criterion cut down past the threshold is the
        documented delete-plus-add case, covered by
        ``test_wholesale_rewrite_reads_as_remove_plus_add``.
        """
        long_criterion = f"{SEED} " + "y" * 120
        trimmed = f"{SEED} " + "y" * 40
        meta, _ = store.create_story("S", "b", acceptance_criteria=[long_criterion])
        assert len(store.get_task(f"{meta.id}-1")[0].title) == 120

        store.update(meta.id, acceptance_criteria=[trimmed])
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-1"
        ]
        _assert_in_sync(store, meta.id, f"{meta.id}-1", trimmed)
        # No longer truncated: the title is the whole criterion again.
        assert store.get_task(f"{meta.id}-1")[0].title == f"Test: {trimmed}"

    def test_criteria_whose_titles_collide_keep_distinct_bodies(self, store):
        """Truncation can make two titles identical; the bodies must not be."""
        shared = "The system must " + "a" * 120
        first, second = f"{shared} ALPHA", f"{shared} BETA"
        meta, _ = store.create_story("S", "b", acceptance_criteria=[first, second])
        assert generate_test_task_title(first) == generate_test_task_title(second)
        store.update(meta.id, acceptance_criteria=[f"{first} revised", second])
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-1"
        ]
        _assert_in_sync(store, meta.id, f"{meta.id}-1", f"{first} revised")
        _assert_in_sync(store, meta.id, f"{meta.id}-2", second)

    def test_rename_syncs_in_place_but_replace_leaves_the_orphan_honest(self, store):
        """Renaming a criterion vs. replacing it are different operations.

        A rename resyncs the existing task.  A replacement creates a new
        one — and the orphan it leaves behind must still quote the
        criterion *it* was generated from, never the replacement's text.
        """
        renamed = f"{SEED} about login and logout"
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])

        store.update(meta.id, acceptance_criteria=[renamed])
        assert store.last_criteria_reconciliation["created_task_ids"] == []
        _assert_in_sync(store, meta.id, f"{meta.id}-1", renamed)

        replacement = "Invoices are exported as PDF once a month"
        store.update(meta.id, acceptance_criteria=[replacement])
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-2"]
        assert [e["task_id"] for e in result["orphaned"]] == [f"{meta.id}-1"]
        # The new task quotes the new criterion...
        _assert_in_sync(store, meta.id, f"{meta.id}-2", replacement)
        # ...and the orphan still quotes its own, unchanged.
        _assert_in_sync(store, meta.id, f"{meta.id}-1", renamed)

    def test_reordering_does_not_smear_bodies_across_tasks(self, store, tmp_project):
        """Association is by text, not by position."""
        criteria = [f"{SEED} one", f"{SEED} two", f"{SEED} three"]
        meta, _ = store.create_story("S", "b", acceptance_criteria=criteria)
        store.update(meta.id, acceptance_criteria=list(reversed(criteria)))
        fresh = _fresh_store(tmp_project)
        for n, criterion in enumerate(criteria, start=1):
            _assert_in_sync(fresh, meta.id, f"{meta.id}-{n}", criterion)

    def test_reorder_and_edit_in_one_call_syncs_only_the_edited_task(self, store):
        criteria = [f"{SEED} one", f"{SEED} two", f"{SEED} three"]
        meta, _ = store.create_story("S", "b", acceptance_criteria=criteria)
        edited_two = f"{SEED} two, now with feeling"
        store.update(
            meta.id, acceptance_criteria=[criteria[2], edited_two, criteria[0]]
        )
        assert store.last_criteria_reconciliation["resynced_task_ids"] == [
            f"{meta.id}-2"
        ]
        _assert_in_sync(store, meta.id, f"{meta.id}-1", criteria[0])
        _assert_in_sync(store, meta.id, f"{meta.id}-2", edited_two)
        _assert_in_sync(store, meta.id, f"{meta.id}-3", criteria[2])

    def test_cache_and_disk_agree_after_a_resync(self, store, tmp_project):
        """A resync that only lands in the cache is not a resync."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        edited = f"{SEED} — reworded ☕"
        store.update(meta.id, acceptance_criteria=[edited])
        cached_meta, cached_body = store.get_task(f"{meta.id}-1")
        disk_meta, disk_body = _fresh_store(tmp_project).get_task(f"{meta.id}-1")
        assert (cached_meta.title, cached_body) == (disk_meta.title, disk_body)

    def test_every_live_task_is_in_sync_after_a_messy_edit_history(
        self, store, tmp_project
    ):
        """The invariant, end to end: no live task ever quotes a dead criterion."""
        meta, _ = store.create_story(
            "S",
            "b",
            acceptance_criteria=[
                "Users can log in with a password",
                "Errors are shown on a failed login",
                "Sessions expire after 30 minutes",
            ],
        )
        for criteria in [
            # edit one
            [
                "Users can log in with a password or a passkey",
                "Errors are shown on a failed login",
                "Sessions expire after 30 minutes",
            ],
            # reorder and add
            [
                "Sessions expire after 30 minutes",
                "Users can log in with a password or a passkey",
                "Errors are shown on a failed login",
                "Admins can revoke a session",
            ],
            # edit two at once and drop one
            [
                "Sessions expire after 60 minutes of inactivity",
                "Users can log in with a password, a passkey or SSO",
                "Admins can revoke a session",
            ],
            # replace one wholesale
            [
                "Sessions expire after 60 minutes of inactivity",
                "Users can log in with a password, a passkey or SSO",
                "Invoices are exported as PDF once a month",
            ],
        ]:
            store.update(meta.id, acceptance_criteria=criteria)

            fresh = _fresh_store(tmp_project)
            live = dict(
                (meta_.id, criterion)
                for meta_, criterion in fresh._test_tasks_for_story(meta.id)
            )
            # Nothing live quotes a criterion the story no longer has...
            assert set(live.values()) <= set(criteria)
            # ...every criterion is covered exactly once...
            assert sorted(live.values()) == sorted(criteria)
            # ...and each of those tasks is fully in sync, title and body.
            for task_id, criterion in live.items():
                _assert_in_sync(fresh, meta.id, task_id, criterion)


class TestBlankCriteriaBreakBodySync:
    """Fixed by US-PM-5-8: a criterion that is empty or ends in whitespace.

    ``generate_test_task_body`` puts the criterion after a ``"> "``
    blockquote marker, so a criterion that is blank or
    trailing-whitespace-terminated used to leave the body ending in
    whitespace.  ``frontmatter.dumps`` strips trailing whitespace from the
    content it writes, so what landed on disk was *not*
    ``generate_test_task_body(story_id, criterion)`` and, for a blank
    criterion, no longer even started with the ``"> "`` prefix the parser
    requires — the task became invisible to reconciliation and every
    subsequent update bred another duplicate.

    The generator now appends an explicit end marker whenever the body
    would otherwise end in whitespace, and the parser is its exact
    inverse.  These tests were ``xfail(strict=True)`` while the defect
    stood; they are ordinary passing tests now, and they are the
    regression guard.  Reported on US-PM-5-3, fixed on US-PM-5-8.
    """

    @pytest.mark.parametrize("criterion", ["", "   ", "\t"])
    def test_blank_criterion_body_round_trips(self, store, tmp_project, criterion):
        meta, _ = store.create_story("S", "b", acceptance_criteria=[criterion])
        _assert_in_sync(_fresh_store(tmp_project), meta.id, f"{meta.id}-1", criterion)

    def test_blank_criterion_does_not_breed_duplicate_tasks(self, store, tmp_project):
        """A trailing comma in pm_update is enough to trigger this."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        store.update(meta.id, acceptance_criteria=[SEED, ""])
        fresh = _fresh_store(tmp_project)
        before = len(fresh.list_tasks(story_id=meta.id, archived=None))
        for _ in range(3):
            store.update(meta.id, acceptance_criteria=[SEED, ""])
        fresh = _fresh_store(tmp_project)
        assert len(fresh.list_tasks(story_id=meta.id, archived=None)) == before

    def test_trailing_whitespace_criterion_converges(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=[SEED])
        padded = f"{SEED} padded  "
        store.update(meta.id, acceptance_criteria=[padded])
        store.update(meta.id, acceptance_criteria=[padded])
        # Second identical update has nothing left to do.
        assert store.last_criteria_reconciliation is None

    def test_trailing_comma_in_pm_update_does_not_breed_tasks(
        self, tmp_project, monkeypatch
    ):
        from projectman import server
        from projectman.store import Store, clear_all_caches

        monkeypatch.chdir(tmp_project)
        server._store_cache.clear()
        clear_all_caches()

        server.pm_create_story("S", "b", acceptance_criteria="Alpha criterion")
        for _ in range(3):
            server.pm_update("US-TST-1", acceptance_criteria="Alpha criterion,")

        clear_all_caches()
        fresh = Store(tmp_project)
        assert len(fresh.list_tasks(story_id="US-TST-1", archived=None)) == 2


# =======================================================================
# US-PM-5-1 — "Editing acceptance criteria adds test tasks for new
# criteria."  The classes above prove reconciliation resyncs and orphans
# correctly; these prove the *add* half of the criterion: that a criterion
# which did not exist before gets a test task, that the task is
# field-for-field what the creation path would have produced, and that the
# add path does not fire when the criterion is not actually new.
# =======================================================================


# Fields that must be identical whichever path produced a test task.
# ``created``/``updated`` are excluded: they are wall-clock dates, not a
# property of the criterion.
GENERATED_TASK_FIELDS = (
    "story_id",
    "title",
    "status",
    "archived",
    "points",
    "tags",
    "depends_on",
    "assignee",
)


def _task_fields(store, task_id):
    """Parsed frontmatter fields plus body — never a substring check."""
    meta, body = store.get_task(task_id)
    dumped = meta.model_dump(mode="json")
    fields = {k: dumped[k] for k in GENERATED_TASK_FIELDS}
    fields["body"] = body
    return fields


def _added_criteria(store, story_id):
    """{task_id: criterion} for the tasks the last reconciliation created."""
    result = store.last_criteria_reconciliation
    created = set(result["created_task_ids"]) if result else set()
    return {
        meta.id: criterion
        for meta, criterion in store._test_tasks_for_story(story_id)
        if meta.id in created
    }


class TestAddedTaskFields:
    """A created task is judged on its parsed fields, not on its title."""

    def test_every_field_of_an_added_task_is_correct(self, store, tmp_project):
        meta, tasks = store.create_story("S", "b")
        assert tasks == []
        criterion = "Sessions expire after 30 minutes of inactivity"
        store.update(meta.id, acceptance_criteria=[criterion])

        new_id = f"{meta.id}-1"
        assert store.last_criteria_reconciliation["created_task_ids"] == [new_id]
        # Read it back off disk, not out of the write-through cache.
        assert _task_fields(_fresh_store(tmp_project), new_id) == {
            "story_id": meta.id,          # linkage
            "title": generate_test_task_title(criterion),
            "status": "todo",             # fresh work, not done/blocked
            "archived": False,            # live on the board
            "points": None,               # unestimated, as create_story leaves it
            "tags": [],
            "depends_on": [],
            "assignee": None,
            "body": generate_test_task_body(meta.id, criterion),
        }

    def test_added_task_is_field_for_field_what_create_story_would_make(
        self, store, tmp_project
    ):
        """The two paths must be indistinguishable, or the audit sees drift.

        Build the same three-criterion story twice — once wholly through
        ``create_story``, once by creating with one criterion and adding the
        other two through ``update`` — and compare task for task.
        """
        criteria = [
            "Users can log in with a password",
            "Errors are shown on a failed login",
            "Sessions expire after 30 minutes",
        ]
        via_create, _ = store.create_story("A", "b", acceptance_criteria=criteria)
        via_update, _ = store.create_story("B", "b", acceptance_criteria=criteria[:1])
        store.update(via_update.id, acceptance_criteria=criteria)
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{via_update.id}-2",
            f"{via_update.id}-3",
        ]

        fresh = _fresh_store(tmp_project)
        for n, criterion in enumerate(criteria, start=1):
            created = _task_fields(fresh, f"{via_create.id}-{n}")
            updated = _task_fields(fresh, f"{via_update.id}-{n}")
            # story_id and the body embed their own story's id by design.
            for record, story in ((created, via_create), (updated, via_update)):
                assert record.pop("story_id") == story.id
                assert record.pop("body") == generate_test_task_body(
                    story.id, criterion
                )
            assert created == updated

    def test_added_task_number_continues_past_manual_tasks(self, store):
        """Ids must not collide with tasks a human already created."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        manual = store.create_task(meta.id, "Do the work", "notes")
        assert manual.id == f"{meta.id}-2"
        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-3"
        ]
        assert criterion_from_test_task_body(
            meta.id, store.get_task(f"{meta.id}-3")[1]
        ) == "Beta two"


class TestAddingToAStoryWithNoCriteria:
    def test_several_criteria_added_to_an_empty_story(self, store, tmp_project):
        """The zero-to-many case: nothing to match against, everything is new."""
        meta, tasks = store.create_story("S", "b")
        assert tasks == []
        criteria = ["First criterion", "Second criterion", "Third criterion"]
        store.update(meta.id, acceptance_criteria=criteria)

        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-{n}" for n in (1, 2, 3)]
        # Nothing existed, so nothing could be unchanged, resynced or orphaned.
        assert (result["unchanged"], result["resync"], result["orphaned"]) == ([], [], [])
        assert _test_task_criteria(_fresh_store(tmp_project), meta.id) == criteria

    def test_empty_list_on_an_empty_story_adds_nothing(self, store):
        meta, _ = store.create_story("S", "b")
        store.update(meta.id, acceptance_criteria=[])
        assert store.list_tasks(story_id=meta.id, archived=None) == []
        assert store.last_criteria_reconciliation is None


class TestAddingSeveralCriteriaInOneCall:
    def test_three_added_at_once_each_get_their_own_task(self, store, tmp_project):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        added = ["Beta two", "Gamma three", "Delta four"]
        store.update(meta.id, acceptance_criteria=["Alpha one"] + added)

        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-{n}" for n in (2, 3, 4)]
        # The pre-existing criterion was matched, not re-created.
        assert [e["criterion"] for e in result["unchanged"]] == ["Alpha one"]
        # Created tasks are ordered as the criteria are, not arbitrarily.
        assert list(_added_criteria(store, meta.id).values()) == added
        fresh = _fresh_store(tmp_project)
        for n, criterion in enumerate(added, start=2):
            _assert_in_sync(fresh, meta.id, f"{meta.id}-{n}", criterion)

    def test_batch_add_does_not_touch_the_criterion_that_was_already_there(
        self, store
    ):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        before = _tasks(store, meta.id)[f"{meta.id}-1"]
        store.update(
            meta.id, acceptance_criteria=["Alpha one", "Beta two", "Gamma three"]
        )
        assert _tasks(store, meta.id)[f"{meta.id}-1"] == before

    def test_a_criterion_listed_twice_gets_a_task_each_time(self, store):
        """Matches ``create_story``, which also loops the list verbatim."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.update(
            meta.id, acceptance_criteria=["Alpha one", "Beta two", "Beta two"]
        )
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-2",
            f"{meta.id}-3",
        ]
        via_create, created_tasks = store.create_story(
            "T", "b", acceptance_criteria=["Alpha one", "Beta two", "Beta two"]
        )
        assert len(created_tasks) == 3
        assert [t.title for t in created_tasks] == [
            store.get_task(f"{meta.id}-{n}")[0].title for n in (1, 2, 3)
        ]


class TestAddingAndRemovingInTheSameCall:
    def test_one_added_one_removed_one_kept(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha one", "Beta two"]
        )
        kept_before = _tasks(store, meta.id)[f"{meta.id}-1"]
        # Deliberately below CRITERION_EDIT_SIMILARITY vs "Beta two" so this
        # is a genuine add-plus-remove, not a rename.
        added = "Invoices are exported as PDF once a month"
        assert criterion_similarity("Beta two", added) < store.CRITERION_EDIT_SIMILARITY
        store.update(meta.id, acceptance_criteria=["Alpha one", added])

        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-3"]
        assert result["resync"] == []
        assert [e["task_id"] for e in result["orphaned"]] == [f"{meta.id}-2"]
        # The kept criterion's task is byte-identical...
        assert _tasks(store, meta.id)[f"{meta.id}-1"] == kept_before
        fresh = _fresh_store(tmp_project)
        # ...the added task quotes the added criterion...
        _assert_in_sync(fresh, meta.id, f"{meta.id}-3", added)
        # ...and the removed criterion's task still quotes its own text,
        # archived rather than rewritten into the newcomer.
        _assert_in_sync(fresh, meta.id, f"{meta.id}-2", "Beta two")
        assert fresh.get_task(f"{meta.id}-2")[0].archived is True

    def test_removing_does_not_free_a_task_for_the_addition_to_reuse(self, store):
        """The add must be an add — never a silent hand-off of the orphan."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        added = "Invoices are exported as PDF once a month"
        store.update(meta.id, acceptance_criteria=[added])
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-2"]
        assert result["resynced_task_ids"] == []
        assert len(store.list_tasks(story_id=meta.id, archived=None)) == 2


class TestNearDuplicateAddsAndTheSimilarityThreshold:
    """Where "a new criterion" ends and "the same criterion, reworded" begins.

    ``CRITERION_EDIT_SIMILARITY`` (0.6) is the only thing separating an add
    from a resync, so the boundary is walked exactly rather than sampled.
    ``criterion_similarity`` of ``"a" * n`` against ``"a" * (n - k) + "b" * k``
    is exactly ``(n - k) / n``, which lets the ratio be dialled to a chosen
    value on either side of the threshold.
    """

    @staticmethod
    def _pair(shared, length=20):
        return "a" * length, "a" * shared + "b" * (length - shared)

    # ``shared == 20`` is excluded: the texts would be identical, which is
    # the no-op case covered by ``TestIdempotency``, not a threshold case.
    @pytest.mark.parametrize("shared", list(range(19, 0, -1)))
    def test_the_flip_is_exactly_at_the_documented_threshold(self, store, shared):
        old, new = self._pair(shared)
        ratio = criterion_similarity(old, new)
        assert ratio == pytest.approx(shared / 20)
        meta, _ = store.create_story("S", "b", acceptance_criteria=[old])
        store.update(meta.id, acceptance_criteria=[new])
        result = store.last_criteria_reconciliation

        if ratio >= store.CRITERION_EDIT_SIMILARITY:
            # Reworded: the existing task is reused, nothing is added.
            assert result["created_task_ids"] == []
            assert result["resynced_task_ids"] == [f"{meta.id}-1"]
        else:
            # A different criterion: added, and the old task is orphaned.
            assert result["created_task_ids"] == [f"{meta.id}-2"]
            assert result["resync"] == []
            assert [e["task_id"] for e in result["orphaned"]] == [f"{meta.id}-1"]
        # Either way, exactly one live task quotes the new criterion.
        live = [c for _m, c in store._test_tasks_for_story(meta.id)]
        assert live == [new]

    def test_the_boundary_ratio_itself_counts_as_an_edit(self, store):
        """0.6 is inclusive — ``>=``, not ``>``."""
        old, new = self._pair(12)
        assert criterion_similarity(old, new) == pytest.approx(
            store.CRITERION_EDIT_SIMILARITY
        )
        meta, _ = store.create_story("S", "b", acceptance_criteria=[old])
        store.update(meta.id, acceptance_criteria=[new])
        assert store.last_criteria_reconciliation["created_task_ids"] == []

    @pytest.mark.parametrize(
        "old,new,expect_add",
        [
            # 0.6471 — a reworded criterion, above the line.
            (
                "Users can log in with a password",
                "Users can reset a forgotten password",
                False,
            ),
            # 0.5143 — shares a prefix and still reads as a different rule.
            (
                "Errors are shown on a failed login",
                "Errors are logged to the audit trail",
                True,
            ),
        ],
    )
    def test_the_threshold_on_real_prose_not_just_synthetic_strings(
        self, store, old, new, expect_add
    ):
        meta, _ = store.create_story("S", "b", acceptance_criteria=[old])
        store.update(meta.id, acceptance_criteria=[new])
        result = store.last_criteria_reconciliation
        assert bool(result["created_task_ids"]) is expect_add
        assert bool(result["resync"]) is not expect_add

    @pytest.mark.parametrize("shared", [20, 15, 12, 11, 6, 0])
    def test_a_near_duplicate_kept_alongside_the_original_is_always_an_add(
        self, store, shared
    ):
        """Similarity never applies while the original text is still present.

        Pass 1 matches by identity, so the original claims its own task
        before the similarity pass runs.  The near-duplicate therefore gets
        its own task at *every* ratio — including ratios well above the
        threshold, where the same text offered as a *replacement* would have
        resynced instead.  Add-vs-resync is decided by whether the old
        criterion survives, not by similarity alone.
        """
        old, near = self._pair(shared)
        meta, _ = store.create_story("S", "b", acceptance_criteria=[old])
        store.update(meta.id, acceptance_criteria=[old, near])
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-2"]
        assert result["resync"] == []
        assert result["orphaned"] == []
        assert [e["criterion"] for e in result["unchanged"]] == [old]
        _assert_in_sync(store, meta.id, f"{meta.id}-2", near)

    def test_a_high_similarity_near_duplicate_still_gets_its_own_task(self, store):
        """The realistic shape: an existing criterion narrowed by a clause."""
        base = "Sessions expire after 30 minutes"
        near = "Sessions expire after 30 minutes of inactivity"
        assert criterion_similarity(base, near) == 1.0
        meta, _ = store.create_story("S", "b", acceptance_criteria=[base])
        store.update(meta.id, acceptance_criteria=[base, near])
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-2"
        ]
        _assert_in_sync(store, meta.id, f"{meta.id}-1", base)
        _assert_in_sync(store, meta.id, f"{meta.id}-2", near)


class TestAddingIsIdempotent:
    def test_re_applying_the_list_after_an_add_creates_nothing(
        self, store, tmp_project
    ):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        criteria = ["Alpha one", "Beta two", "Gamma three"]
        store.update(meta.id, acceptance_criteria=criteria)
        after_add = {m.id for m in _fresh_store(tmp_project).list_tasks(
            story_id=meta.id, archived=None
        )}
        assert len(after_add) == 3

        for _ in range(4):
            store.update(meta.id, acceptance_criteria=list(criteria))
            # Not merely "created nothing" — reconciliation never even ran.
            assert store.last_criteria_reconciliation is None
        assert {
            m.id
            for m in _fresh_store(tmp_project).list_tasks(
                story_id=meta.id, archived=None
            )
        } == after_add

    def test_adding_the_same_criterion_twice_in_a_row_adds_it_once(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-2"
        ]
        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])
        assert store.last_criteria_reconciliation is None
        assert len(store.list_tasks(story_id=meta.id, archived=None)) == 2


class TestAddingWhenAnExistingTestTaskIsDoneOrArchived:
    def test_a_done_test_task_is_left_alone_by_an_add(self, store, tmp_project):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.update(f"{meta.id}-1", status="done", assignee="ryan")
        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])

        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-2"
        ]
        done_meta, done_body = _fresh_store(tmp_project).get_task(f"{meta.id}-1")
        assert done_meta.status.value == "done"
        assert done_meta.assignee == "ryan"
        assert done_meta.archived is False
        assert done_body == generate_test_task_body(meta.id, "Alpha one")

    def test_an_add_that_also_orphans_a_done_task_flags_rather_than_archives(
        self, store
    ):
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha one", "Beta two"]
        )
        store.update(f"{meta.id}-2", status="done")
        store.update(
            meta.id,
            acceptance_criteria=["Alpha one", "Invoices are exported as PDF monthly"],
        )
        result = store.last_criteria_reconciliation
        assert result["created_task_ids"] == [f"{meta.id}-3"]
        assert result["archived_task_ids"] == []
        assert result["flagged_task_ids"] == [f"{meta.id}-2"]
        assert store.get_task(f"{meta.id}-2")[0].status.value == "done"

    def test_an_archived_task_for_a_removed_criterion_does_not_disturb_an_add(
        self, store
    ):
        """The clean archived case: the archived task's criterion is gone too."""
        meta, _ = store.create_story(
            "S", "b", acceptance_criteria=["Alpha one", "Beta two"]
        )
        store.archive(f"{meta.id}-2")
        before = _tasks(store, meta.id)[f"{meta.id}-2"]
        store.update(meta.id, acceptance_criteria=["Alpha one", "Gamma three"])
        assert store.last_criteria_reconciliation["created_task_ids"] == [
            f"{meta.id}-3"
        ]
        assert _tasks(store, meta.id)[f"{meta.id}-2"] == before


class TestArchivedTaskForALiveCriterionIsNotResurrectedByAnAdd:
    """Defect found by US-PM-5-1, fixed by US-PM-5-9.

    ``plan_criteria_reconciliation`` used to match only against
    ``_test_tasks_for_story(story_id)``, which excludes archived tasks.  So
    when a live criterion's test task had been archived, that criterion
    fell into the plan's ``create`` bucket — and any unrelated edit to the
    criteria list made ``Store.update`` create a second, live task quoting
    a criterion that was already there.  The story's criterion is
    "adds test tasks for **new** criteria"; that added one for an old one.

    The sharper evidence was that ``detect_criteria_drift`` — the detector
    pm_audit reports from — deliberately suppressed exactly this criterion
    ("an archived test task was retired on purpose", US-PM-16) and so
    reported ``missing == []`` for it.  ``plan_criteria_reconciliation``'s
    own docstring states the contract the pair then broke: *"pm_audit and
    the reconciler must never disagree about what counts as a match."*
    The audit said the story was clean; the very next ``pm_update`` silently
    grew a duplicate.

    Resolved in the reconciler's favour: the plan now has a third pass that
    diverts an archived-covered criterion out of ``create`` and into
    ``retired``, and ``detect_criteria_drift`` dropped its private
    ``_covered_by_archived`` filter and reports ``plan["create"]``
    verbatim.  Archiving is neither deletion nor completion (US-PM-16) and
    ``Store.unarchive``/``pm_restore`` is the way back (US-PM-5-6), so the
    reconciler declines to act rather than un-archiving behind the human's
    decision.  These three were ``xfail(strict=True)`` while the defect
    stood; they are ordinary regression tests now.
    """

    def test_add_creates_a_task_only_for_the_genuinely_new_criterion(
        self, store, tmp_project
    ):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.archive(f"{meta.id}-1")
        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])

        created = _added_criteria(store, meta.id)
        assert list(created.values()) == ["Beta two"]
        # And no live task duplicates the archived one's criterion.
        live = [c for _m, c in _fresh_store(tmp_project)._test_tasks_for_story(meta.id)]
        assert live.count("Alpha one") == 0

    def test_the_audit_and_the_reconciler_agree_on_what_is_new(self, store):
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.archive(f"{meta.id}-1")
        criteria = ["Alpha one", "Beta two"]

        drift = store.detect_criteria_drift(meta.id, criteria)
        plan = store.plan_criteria_reconciliation(meta.id, criteria)
        assert [e["criterion"] for e in plan["create"]] == [
            e["criterion"] for e in drift["missing"]
        ]

    def test_pm_update_does_not_resurrect_an_archived_task_criterion(
        self, tmp_project, monkeypatch
    ):
        from projectman import server
        from projectman.store import Store, clear_all_caches

        monkeypatch.chdir(tmp_project)
        server._store_cache.clear()
        clear_all_caches()

        server.pm_create_story("S", "b", acceptance_criteria="Alpha one")
        server.pm_update("US-TST-1-1", status="done")
        server.pm_archive("US-TST-1-1")
        out = server.pm_update("US-TST-1", acceptance_criteria="Alpha one,Beta two")
        # Declining to act is still reported: the caller is told which
        # archived task stood in, so it can pm_restore if that is wanted.
        import yaml as _yaml

        assert _yaml.safe_load(out)["test_tasks"]["retired"] == [
            {"id": "US-TST-1-1", "criterion": "Alpha one"}
        ]

        clear_all_caches()
        fresh = Store(tmp_project)
        live = [c for _m, c in fresh._test_tasks_for_story("US-TST-1")]
        assert live == ["Beta two"]


# ---------------------------------------------------------------------------
# US-PM-5-9 — the agreement contract itself.
#
# ``detect_criteria_drift`` is documented as a read-only *projection* of
# ``plan_criteria_reconciliation``, not a second matcher: "pm_audit and the
# reconciler must never disagree about what counts as a match."  The defect
# this task fixed was exactly a disagreement — each side had its own idea of
# what an archived test task covers — so the contract is asserted here
# directly, over a matrix of store states rather than one scenario.
# ---------------------------------------------------------------------------


def _mutate_nothing(store, sid):
    pass


def _archive_first(store, sid):
    store.archive(f"{sid}-1")


def _archive_second(store, sid):
    store.archive(f"{sid}-2")


def _archive_all(store, sid):
    store.archive(f"{sid}-1")
    store.archive(f"{sid}-2")


def _work_then_archive_first(store, sid):
    store.update(f"{sid}-1", status="done", assignee="ryan")
    store.archive(f"{sid}-1")


def _work_on_first(store, sid):
    store.update(f"{sid}-1", status="in-progress", assignee="ryan")


def _rewrite_first_body(store, sid):
    store.update(f"{sid}-1", body="I own this task now, my own words entirely")


TWO = ["Alpha one", "Beta two"]

# name -> (initial criteria, mutation, criteria to reconcile against)
AGREEMENT_CASES = {
    "nothing changed": (TWO, _mutate_nothing, TWO),
    "one added": (TWO, _mutate_nothing, TWO + ["Gamma three"]),
    "one removed": (TWO, _mutate_nothing, ["Alpha one"]),
    "all removed": (TWO, _mutate_nothing, []),
    "one reworded": (TWO, _mutate_nothing, ["Alpha one edited slightly", "Beta two"]),
    "reordered": (TWO, _mutate_nothing, ["Beta two", "Alpha one"]),
    "replaced wholesale": (TWO, _mutate_nothing, ["Wholly unrelated text here"]),
    # The archived family — where the two sides used to part company.
    "live criterion, task archived": (TWO, _archive_first, TWO),
    "live criterion, task archived, plus an add": (
        TWO,
        _archive_first,
        TWO + ["Gamma three"],
    ),
    "archived task for a removed criterion": (TWO, _archive_second, ["Alpha one"]),
    "every task archived, criteria intact": (TWO, _archive_all, TWO),
    "archived after work, criterion still live": (TWO, _work_then_archive_first, TWO),
    "archived task's criterion reworded": (
        TWO,
        _archive_first,
        ["Alpha one edited slightly", "Beta two"],
    ),
    # Touched-but-live, and invisible-to-the-matcher, for contrast.
    "work started, criterion removed": (TWO, _work_on_first, ["Beta two"]),
    "human rewrote the body": (TWO, _rewrite_first_body, ["Beta two"]),
}


def _covered(store, story_id, criteria):
    """Each side's verdict on which criteria already have a test task.

    Returns ``(drift_covered, plan_covered)`` as sets of criterion text.  A
    criterion is "covered" when the detector does not call it missing, and
    when the plan does not put it in ``create`` — the same question asked of
    the two sides that must never disagree.
    """
    drift = store.detect_criteria_drift(story_id, list(criteria))
    plan = store.plan_criteria_reconciliation(story_id, list(criteria))
    drift_covered = set(criteria) - {e["criterion"] for e in drift["missing"]}
    plan_covered = set(criteria) - {e["criterion"] for e in plan["create"]}
    return drift_covered, plan_covered, drift, plan


class TestDriftIsAProjectionOfThePlan:
    @pytest.mark.parametrize("case", list(AGREEMENT_CASES))
    def test_the_two_sides_agree_on_which_criteria_are_covered(
        self, store, tmp_project, case
    ):
        initial, mutate, criteria = AGREEMENT_CASES[case]
        meta, _ = store.create_story("S", "b", acceptance_criteria=list(initial))
        mutate(store, meta.id)

        fresh = _fresh_store(tmp_project)
        drift_covered, plan_covered, drift, plan = _covered(fresh, meta.id, criteria)
        assert drift_covered == plan_covered, (case, drift, plan)
        # Not merely the same set — ``missing`` is ``create`` verbatim,
        # entry for entry, index included.
        assert drift["missing"] == [
            {"criterion": e["criterion"], "index": e["index"]} for e in plan["create"]
        ]

    @pytest.mark.parametrize("case", list(AGREEMENT_CASES))
    def test_the_two_sides_still_agree_after_the_plan_is_applied(
        self, store, tmp_project, case
    ):
        """The audit's verdict must survive the update it describes.

        Reconciling and then re-asking is the sequence that exposed the
        defect: the audit said clean, the update created a duplicate, and a
        second audit would have said clean again while the duplicate sat
        there.  So assert agreement *after* the write too, and that no
        criterion ends up quoted by two live test tasks.
        """
        initial, mutate, criteria = AGREEMENT_CASES[case]
        meta, _ = store.create_story("S", "b", acceptance_criteria=list(initial))
        mutate(store, meta.id)
        store.update(meta.id, acceptance_criteria=list(criteria))

        fresh = _fresh_store(tmp_project)
        drift_covered, plan_covered, drift, plan = _covered(fresh, meta.id, criteria)
        assert drift_covered == plan_covered, (case, drift, plan)
        assert drift["missing"] == [
            {"criterion": e["criterion"], "index": e["index"]} for e in plan["create"]
        ]

        live = [c for _m, c in fresh._test_tasks_for_story(meta.id)]
        assert len(live) == len(set(live)), (case, live)

    @pytest.mark.parametrize("case", list(AGREEMENT_CASES))
    def test_reconciling_twice_creates_nothing_the_second_time(
        self, store, tmp_project, case
    ):
        """The duplicate the defect bred appeared on the *second* edit."""
        initial, mutate, criteria = AGREEMENT_CASES[case]
        meta, _ = store.create_story("S", "b", acceptance_criteria=list(initial))
        mutate(store, meta.id)
        store.update(meta.id, acceptance_criteria=list(criteria))
        before = {m.id for m in store.list_tasks(story_id=meta.id, archived=None)}

        store.update(meta.id, acceptance_criteria=list(criteria))
        after = {
            m.id
            for m in _fresh_store(tmp_project).list_tasks(story_id=meta.id, archived=None)
        }
        assert after == before, case

    def test_a_criterion_an_archived_task_covers_is_reported_as_retired(self, store):
        """The plan says *why* it created nothing — it does not just go quiet."""
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.archive(f"{meta.id}-1")
        plan = store.plan_criteria_reconciliation(meta.id, ["Alpha one", "Beta two"])
        assert plan["create"] == [{"criterion": "Beta two", "index": 1}]
        assert plan["retired"] == [
            {
                "criterion": "Alpha one",
                "index": 0,
                "task_id": f"{meta.id}-1",
                "old_criterion": "Alpha one",
            }
        ]

    def test_the_archived_task_is_left_archived_not_restored(self, store, tmp_project):
        """Archiving is a decision (US-PM-16); the reconciler does not undo it.

        The alternative resolution — silently un-archiving — was rejected
        precisely here: ``Store.unarchive`` exists so a human can reverse
        the decision deliberately.
        """
        meta, _ = store.create_story("S", "b", acceptance_criteria=["Alpha one"])
        store.archive(f"{meta.id}-1")
        before = store._task_path(f"{meta.id}-1").read_bytes()
        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])

        fresh = _fresh_store(tmp_project)
        assert fresh._task_path(f"{meta.id}-1").read_bytes() == before
        assert fresh.get_task(f"{meta.id}-1")[0].archived is True
        # And the way back is still open.
        fresh.unarchive(f"{meta.id}-1")
        assert _fresh_store(tmp_project).get_task(f"{meta.id}-1")[0].archived is False

    def test_the_audit_stays_clean_through_the_update_it_blessed(
        self, store, tmp_project
    ):
        """End to end: pm_audit's verdict and pm_update's action must match."""
        from projectman.audit import run_audit
        from projectman.store import clear_all_caches

        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha one"]
        )
        store.archive(f"{meta.id}-1")
        clear_all_caches()
        before = run_audit(tmp_project)
        assert "with no test task" not in before

        store.update(meta.id, acceptance_criteria=["Alpha one", "Beta two"])
        clear_all_caches()
        after = run_audit(tmp_project)
        assert "with no test task" not in after
        live = [c for _m, c in _fresh_store(tmp_project)._test_tasks_for_story(meta.id)]
        assert live == ["Beta two"]


# ---------------------------------------------------------------------------
# US-PM-5-2 — verification of the story criterion
#
#   "Test tasks for removed criteria are flagged rather than silently deleted
#    if work has started"
#
# The shipped policy (US-PM-5-6) is *never delete*: an orphan with no work
# against it is archived (reversible), an orphan with work is left
# byte-for-byte alone and flagged.  These tests pin the boundary between the
# two branches, what "flagged" means concretely, and that nothing carrying
# work can be irrecoverably destroyed.
#
# Single-signal coverage lives in tests/test_orphan_removal_policy.py; what
# follows deliberately does not repeat it.  It adds the combination truth
# table, the revert-to-pristine edge, the run-log boundary, multi-criterion
# and all-criteria removals, and the recoverability proof.
# ---------------------------------------------------------------------------

KEPT = "Alpha criterion"
DROPPED = "Beta criterion"


def _story(store, *criteria):
    meta, _ = store.create_story("S", "b", acceptance_criteria=list(criteria))
    return meta.id


def _file_bytes(store, task_id):
    return store._task_path(task_id).read_bytes()


def _orphan_for(store, task_id):
    """The reconciliation record's verdict for one task."""
    record = store.last_criteria_reconciliation
    assert record is not None, "update() did not reconcile at all"
    entries = [o for o in record["orphaned"] if o["task_id"] == task_id]
    assert len(entries) == 1, record["orphaned"]
    return entries[0]


def _log_path(tmp_project, task_id):
    return tmp_project / ".project" / "logs" / f"{task_id}.jsonl"


def _audit_text(tmp_project):
    from projectman.audit import run_audit
    from projectman.store import clear_all_caches

    clear_all_caches()
    return run_audit(tmp_project)


STALE_FINDING = "quoting an acceptance criterion that no longer exists"


class TestWhatFlaggedMeansConcretely:
    """"Flagged" is not prose — pin the observable consequences."""

    def test_the_task_file_is_left_byte_for_byte_alone(self, store):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", assignee="ryan")
        before = _file_bytes(store, f"{sid}-2")
        store.update(sid, acceptance_criteria=[KEPT])
        assert _file_bytes(store, f"{sid}-2") == before

    def test_every_parsed_field_survives_the_removal(self, store, tmp_project):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        store.update(sid, acceptance_criteria=[KEPT])

        fresh = _fresh_store(tmp_project)
        meta, body = fresh.get_task(f"{sid}-2")
        assert meta.archived is False
        assert meta.status.value == "in-progress"
        assert meta.assignee == "ryan"
        assert meta.title == generate_test_task_title(DROPPED)
        # The dropped criterion's text is still recoverable from the body —
        # the task is the only surviving record that it was ever agreed.
        assert criterion_from_test_task_body(sid, body) == DROPPED

    def test_a_flagged_task_stays_in_the_active_working_set(self, store, tmp_project):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress")
        store.update(sid, acceptance_criteria=[KEPT])
        fresh = _fresh_store(tmp_project)
        assert f"{sid}-2" in [t.id for t in fresh.list_tasks(story_id=sid, archived=False)]

    def test_the_verdict_is_machine_readable(self, store):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress")
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["has_work"] is True
        assert orphan["work_reasons"] == ["status-not-todo"]
        assert orphan["criterion"] == DROPPED
        record = store.last_criteria_reconciliation
        assert record["flagged_task_ids"] == [f"{sid}-2"]
        assert record["archived_task_ids"] == []

    def test_the_flag_outlives_the_call_that_raised_it(self, store, tmp_project):
        """The response is transient; the durable flag is pm_audit's."""
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        store.update(sid, acceptance_criteria=[KEPT])

        fresh = _fresh_store(tmp_project)
        drift = fresh.detect_criteria_drift(sid)
        assert [e["task_id"] for e in drift["stale"]] == [f"{sid}-2"]

        report = _audit_text(tmp_project)
        assert STALE_FINDING in report

    def test_the_archive_branch_is_a_closed_decision_the_audit_stays_quiet(
        self, store, tmp_project
    ):
        """Contrast: an untouched orphan is archived, so nothing nags."""
        sid = _story(store, KEPT, DROPPED)
        store.update(sid, acceptance_criteria=[KEPT])
        fresh = _fresh_store(tmp_project)
        assert fresh.detect_criteria_drift(sid) == {"missing": [], "stale": []}
        assert STALE_FINDING not in _audit_text(tmp_project)


class TestTheWorkStartedTruthTable:
    """Every combination of the three signals US-PM-5-6 named.

    ``status-not-todo``, ``assigned`` and ``run-log-entries``, each alone and
    in every combination, against the same story.  The all-false row is the
    control: it is the only one that may be archived.
    """

    @staticmethod
    def _apply(store, task_id, status_moved, assigned, logged):
        if status_moved:
            store.update(task_id, status="in-progress")
        if assigned:
            store.update(task_id, assignee="ryan")
        if logged:
            store._append_run_log(task_id, outcome="failed", note="tried")

    @pytest.mark.parametrize("logged", [False, True], ids=["no-log", "log"])
    @pytest.mark.parametrize("assigned", [False, True], ids=["unassigned", "assigned"])
    @pytest.mark.parametrize("status_moved", [False, True], ids=["todo", "moved"])
    def test_every_combination(self, store, tmp_project, status_moved, assigned, logged):
        sid = _story(store, KEPT, DROPPED)
        self._apply(store, f"{sid}-2", status_moved, assigned, logged)
        before = _file_bytes(store, f"{sid}-2")

        store.update(sid, acceptance_criteria=[KEPT])

        expected = []
        if status_moved:
            expected.append("status-not-todo")
        if assigned:
            expected.append("assigned")
        if logged:
            expected.append("run-log-entries")

        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["work_reasons"] == expected
        assert orphan["has_work"] is bool(expected)
        assert orphan["action"] == (
            ORPHAN_ACTION_FLAG if expected else ORPHAN_ACTION_ARCHIVE
        )

        meta, _ = _fresh_store(tmp_project).get_task(f"{sid}-2")
        assert meta.archived is (not expected)
        if expected:
            # Flagged: not one byte moved.
            assert _file_bytes(store, f"{sid}-2") == before
        # Either way the file is still there.
        assert store._task_path(f"{sid}-2").exists()

    @pytest.mark.parametrize("status", ["in-progress", "review", "done", "blocked"])
    def test_each_non_todo_status_combines_with_a_run_log(self, store, status):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status=status)
        store._append_run_log(f"{sid}-2", outcome="partial", note="halfway")
        before = _file_bytes(store, f"{sid}-2")
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["status-not-todo", "run-log-entries"]
        assert orphan["status"] == status
        assert _file_bytes(store, f"{sid}-2") == before


class TestTouchedThenRevertedToPristine:
    """The policy reads current state, not history — pin what that costs.

    A task moved and moved back carries no surviving evidence of work, so it
    is archived.  That is defensible only because archiving is reversible and
    is reported; both are asserted here rather than assumed.
    """

    def test_status_moved_and_moved_back_is_archived_not_flagged(self, store):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress")
        store.update(f"{sid}-2", status="todo")
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["action"] == ORPHAN_ACTION_ARCHIVE
        assert orphan["work_reasons"] == []
        # Archived, but announced — not silent — and reversible.
        assert store.last_criteria_reconciliation["archived_task_ids"] == [f"{sid}-2"]
        store.unarchive(f"{sid}-2")
        meta, body = store.get_task(f"{sid}-2")
        assert meta.archived is False
        assert criterion_from_test_task_body(sid, body) == DROPPED

    def test_a_run_log_entry_survives_the_revert_and_still_flags(self, store):
        """The run log is the one signal a revert cannot erase."""
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", outcome="partial", note="began")
        store.update(f"{sid}-2", status="todo", assignee="")
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["status"] == "todo"
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["run-log-entries"]

    def test_unassigning_returns_the_task_to_pristine(self, store):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", assignee="ryan")
        store.update(f"{sid}-2", assignee="")
        store.update(sid, acceptance_criteria=[KEPT])
        assert _orphan_for(store, f"{sid}-2")["action"] == ORPHAN_ACTION_ARCHIVE

    def test_renaming_back_to_the_generated_title_returns_it_to_pristine(self, store):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", title="Mine now")
        store.update(f"{sid}-2", title=generate_test_task_title(DROPPED))
        store.update(sid, acceptance_criteria=[KEPT])
        assert _orphan_for(store, f"{sid}-2")["action"] == ORPHAN_ACTION_ARCHIVE


class TestRunLogBoundary:
    """"No run-log entries" vs. "run-log entries", at the file level."""

    def test_no_run_log_file_at_all_is_untouched(self, store, tmp_project):
        sid = _story(store, KEPT, DROPPED)
        assert not _log_path(tmp_project, f"{sid}-2").exists()
        store.update(sid, acceptance_criteria=[KEPT])
        assert _orphan_for(store, f"{sid}-2")["work_reasons"] == []

    @pytest.mark.parametrize("content", ["", "\n", "   \n\n  \n"], ids=["empty", "newline", "blank-lines"])
    def test_an_empty_run_log_file_is_untouched(self, store, tmp_project, content):
        sid = _story(store, KEPT, DROPPED)
        path = _log_path(tmp_project, f"{sid}-2")
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["work_reasons"] == []
        assert orphan["action"] == ORPHAN_ACTION_ARCHIVE

    @pytest.mark.parametrize("entries", [1, 2, 5])
    def test_any_number_of_real_entries_flags(self, store, entries):
        sid = _story(store, KEPT, DROPPED)
        for i in range(entries):
            store._append_run_log(f"{sid}-2", outcome="info", note=f"attempt {i}")
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["run-log-entries"]

    @pytest.mark.parametrize("logged", [False, True], ids=["archived", "flagged"])
    def test_the_run_log_file_is_never_removed_by_either_branch(
        self, store, tmp_project, logged
    ):
        sid = _story(store, KEPT, DROPPED)
        if logged:
            store._append_run_log(f"{sid}-2", outcome="failed", note="tried")
        else:
            # An untouched orphan can still have a log file from a sibling
            # process; give it one that parses to nothing.
            path = _log_path(tmp_project, f"{sid}-2")
            path.parent.mkdir(exist_ok=True)
            path.write_text("")
        before = _log_path(tmp_project, f"{sid}-2").read_bytes()
        store.update(sid, acceptance_criteria=[KEPT])
        assert _log_path(tmp_project, f"{sid}-2").read_bytes() == before

    def test_an_unreadable_run_log_counts_as_work(self, store, tmp_project):
        """Was xfail(strict=True) until US-PM-5-10; now the regression guard.

        ``get_run_log`` skips malformed lines, so a wholly corrupt log parsed
        as empty and the task was archived instead of flagged — the fail-safe
        inverted.  ``_run_log_shows_activity`` asks the file, not the parser.
        """
        sid = _story(store, KEPT, DROPPED)
        path = _log_path(tmp_project, f"{sid}-2")
        path.parent.mkdir(exist_ok=True)
        path.write_text("{not json at all}\n")
        store.update(sid, acceptance_criteria=[KEPT])
        orphan = _orphan_for(store, f"{sid}-2")
        assert orphan["action"] == ORPHAN_ACTION_FLAG
        assert orphan["work_reasons"] == ["run-log-entries"]


class TestRemovingSeveralCriteriaAtOnce:
    def test_a_mix_of_touched_and_untouched_is_partitioned(self, store, tmp_project):
        sid = _story(store, KEPT, "Beta criterion", "Gamma criterion", "Delta criterion")
        store.update(f"{sid}-3", status="in-progress")
        store._append_run_log(f"{sid}-4", outcome="failed", note="tried")
        flagged_bytes = {t: _file_bytes(store, t) for t in (f"{sid}-3", f"{sid}-4")}

        store.update(sid, acceptance_criteria=[KEPT])

        record = store.last_criteria_reconciliation
        assert record["archived_task_ids"] == [f"{sid}-2"]
        assert record["flagged_task_ids"] == [f"{sid}-3", f"{sid}-4"]
        assert set(record["archived_task_ids"]) | set(record["flagged_task_ids"]) == {
            o["task_id"] for o in record["orphaned"]
        }

        fresh = _fresh_store(tmp_project)
        assert fresh.get_task(f"{sid}-2")[0].archived is True
        for task_id, raw in flagged_bytes.items():
            assert fresh.get_task(task_id)[0].archived is False
            assert _file_bytes(fresh, task_id) == raw
        # The kept criterion's task is not in scope at all.
        assert fresh.get_task(f"{sid}-1")[0].archived is False
        assert all(o["task_id"] != f"{sid}-1" for o in record["orphaned"])

    def test_removing_every_criterion_with_a_mix(self, store, tmp_project):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        flagged = _file_bytes(store, f"{sid}-2")

        store.update(sid, acceptance_criteria=[])

        record = store.last_criteria_reconciliation
        assert record["archived_task_ids"] == [f"{sid}-1"]
        assert record["flagged_task_ids"] == [f"{sid}-2"]
        fresh = _fresh_store(tmp_project)
        story_meta, _ = fresh.get_story(sid)
        assert story_meta.acceptance_criteria == []
        # Both criteria are gone from the story and still readable from disk.
        assert criterion_from_test_task_body(sid, fresh.get_task(f"{sid}-1")[1]) == KEPT
        assert criterion_from_test_task_body(sid, fresh.get_task(f"{sid}-2")[1]) == DROPPED
        assert _file_bytes(fresh, f"{sid}-2") == flagged

    def test_removing_every_criterion_when_all_have_work(self, store, tmp_project):
        sid = _story(store, KEPT, DROPPED, "Gamma criterion")
        store.update(f"{sid}-1", status="done")
        store.update(f"{sid}-2", assignee="ryan")
        store._append_run_log(f"{sid}-3", outcome="blocked", note="stuck")

        store.update(sid, acceptance_criteria=[])

        record = store.last_criteria_reconciliation
        assert record["archived_task_ids"] == []
        assert record["flagged_task_ids"] == [f"{sid}-{n}" for n in (1, 2, 3)]
        fresh = _fresh_store(tmp_project)
        live = [t.id for t in fresh.list_tasks(story_id=sid, archived=False)]
        assert live == [f"{sid}-{n}" for n in (1, 2, 3)]

    def test_no_task_file_is_ever_removed_by_a_hostile_edit_sequence(
        self, store, tmp_project
    ):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress")
        tasks_dir = tmp_project / ".project" / "tasks"
        seen = {p.name for p in tasks_dir.glob("*.md")}
        for text in ("Wholly different one", "Wholly different two", ""):
            store.update(sid, acceptance_criteria=[text] if text else [])
            now = {p.name for p in tasks_dir.glob("*.md")}
            assert seen <= now, "a task file disappeared"
            seen = now


class TestATouchedTaskWhoseCriterionSurvives:
    """Work-in-flight against a criterion that was edited, not removed."""

    def test_an_edited_criterion_resyncs_without_orphaning_or_archiving(
        self, store, tmp_project
    ):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        store.update(sid, acceptance_criteria=[KEPT, f"{DROPPED} revised"])

        record = store.last_criteria_reconciliation
        assert record["orphaned"] == []
        assert record["archived_task_ids"] == []
        assert record["resynced_task_ids"] == [f"{sid}-2"]

        meta, body = _fresh_store(tmp_project).get_task(f"{sid}-2")
        assert meta.archived is False
        assert meta.status.value == "in-progress"
        assert meta.assignee == "ryan"
        assert criterion_from_test_task_body(sid, body) == f"{DROPPED} revised"

    def test_a_surviving_criterion_task_is_untouched_while_a_sibling_is_removed(
        self, store, tmp_project
    ):
        sid = _story(store, KEPT, DROPPED, "Gamma criterion")
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        before = _file_bytes(store, f"{sid}-2")
        store.update(sid, acceptance_criteria=[KEPT, DROPPED])

        record = store.last_criteria_reconciliation
        assert [o["task_id"] for o in record["orphaned"]] == [f"{sid}-3"]
        assert _file_bytes(store, f"{sid}-2") == before
        assert _fresh_store(tmp_project).get_task(f"{sid}-2")[0].archived is False


class TestNothingWithWorkIsIrrecoverablyDestroyed:
    def test_a_flagged_task_is_fully_readable_after_a_process_restart(
        self, store, tmp_project
    ):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        store._append_run_log(f"{sid}-2", outcome="partial", note="half done")
        store.update(sid, acceptance_criteria=[KEPT])

        fresh = _fresh_store(tmp_project)
        meta, body = fresh.get_task(f"{sid}-2")
        assert meta.status.value == "in-progress"
        assert criterion_from_test_task_body(sid, body) == DROPPED
        log = fresh.get_run_log(f"{sid}-2")
        assert [e.note for e in log] == ["half done"]

    def test_an_archived_task_is_one_unarchive_from_being_back(
        self, store, tmp_project
    ):
        sid = _story(store, KEPT, DROPPED)
        before_meta, before_body = store.get_task(f"{sid}-2")
        store.update(sid, acceptance_criteria=[KEPT])

        fresh = _fresh_store(tmp_project)
        fresh.unarchive(f"{sid}-2")
        after_meta, after_body = fresh.get_task(f"{sid}-2")
        assert after_meta.archived is False
        assert after_meta.status == before_meta.status
        assert after_meta.title == before_meta.title
        assert after_body == before_body
        assert f"{sid}-2" in [
            t.id for t in fresh.list_tasks(story_id=sid, archived=False)
        ]

    def test_no_criterion_ever_agreed_is_lost_across_repeated_rewrites(
        self, store, tmp_project
    ):
        """Every criterion the story ever carried stays readable on disk."""
        sid = _story(store, KEPT)
        history = [KEPT]
        for text in ("Second wholly unrelated wording", "Third entirely other text"):
            # Give the live task work so both branches of the policy are used.
            live = _fresh_store(tmp_project)._test_tasks_for_story(sid)
            store.update(live[-1][0].id, status="in-progress")
            store.update(sid, acceptance_criteria=[text])
            history.append(text)

        fresh = _fresh_store(tmp_project)
        recoverable = {
            criterion
            for _meta, criterion in fresh._test_tasks_for_story(sid, archived=None)
        }
        assert set(history) <= recoverable


class TestFlaggedOrphanIsInvisibleWhenNoCriteriaRemain:
    """Defect found by US-PM-5-2: the durable flag vanishes at zero criteria.

    ``Store.detect_criteria_drift`` short-circuits on a story with no
    acceptance criteria ("there is nothing to be out of sync with") and
    pm_audit's Check 17 skips such stories outright.  So when *every*
    criterion is removed, a test task that had work against it is left live,
    still quoting a criterion that no longer exists, and no audit ever
    mentions it again — the ``pm_update`` response is the only notice, and it
    is gone the moment the call returns.

    Nothing is deleted, so the destructive half of the criterion holds; what
    fails is "flagged".  A stale test task is stale whether or not the story
    has other criteria left: ``stale`` does not depend on the criteria list
    the way ``missing`` does, so the early return is too broad.

    Fixed on US-PM-5-10: ``detect_criteria_drift`` now computes ``stale``
    without the empty-criteria short circuit (the guard survives only around
    ``missing``, which really is defined relative to the criteria list), and
    audit.py's Check 17 no longer skips criteria-less stories.  These tests
    were ``xfail(strict=True)`` while the defect stood; they are ordinary
    passing tests now, and they are the regression guard.
    """

    @staticmethod
    def _flagged_orphan_on_a_criteria_less_story(store):
        sid = _story(store, KEPT, DROPPED)
        store.update(f"{sid}-2", status="in-progress", assignee="ryan")
        store.update(sid, acceptance_criteria=[])
        assert store.last_criteria_reconciliation["flagged_task_ids"] == [f"{sid}-2"]
        return sid

    def test_drift_still_reports_the_stale_task(self, store, tmp_project):
        sid = self._flagged_orphan_on_a_criteria_less_story(store)
        fresh = _fresh_store(tmp_project)
        assert [e["task_id"] for e in fresh.detect_criteria_drift(sid)["stale"]] == [
            f"{sid}-2"
        ]

    def test_the_audit_surfaces_the_flagged_task(self, store, tmp_project):
        self._flagged_orphan_on_a_criteria_less_story(store)
        assert STALE_FINDING in _audit_text(tmp_project)
