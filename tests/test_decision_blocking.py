"""Open decisions blocking a task (US-PM-64-6).

Every store-backed test runs against the tmp_path-isolated ``store`` fixture;
nothing here touches the real ``.project``.
"""

from datetime import date

import pytest

from projectman.decisions import blocking_decisions
from projectman.models import DecisionFrontmatter, StoryFrontmatter, TaskFrontmatter

DESC = "A description long enough to be a real task body for these tests."


@pytest.fixture
def tree(store):
    """EPIC-TST-1 > US-TST-1 > US-TST-1-1, US-TST-1-2; US-TST-2 (no epic) > US-TST-2-1."""
    store.create_epic("Epic", "Epic description")
    store.create_story("Story one", "Story description")
    store.update("US-TST-1", epic_id="EPIC-TST-1")
    store.create_task("US-TST-1", "Task one", DESC)
    store.create_task("US-TST-1", "Task two", DESC)
    store.create_story("Story two", "Story description")
    store.create_task("US-TST-2", "Task three", DESC)
    return store


def _ids(decisions):
    return [d.id for d in decisions]


def _task(store, task_id):
    return store.get_task(task_id)[0]


def _preloaded(store):
    return {
        "decisions": store.list_decisions(),
        "stories": {s.id: s for s in store.list_stories()},
    }


class TestBlockingDecisions:
    def test_blocks_task_directly(self, tree):
        tree.create_decision("Q?", blocks=["US-TST-1-1"])
        assert _ids(blocking_decisions(_task(tree, "US-TST-1-1"), tree)) == ["DEC-TST-1"]
        assert blocking_decisions(_task(tree, "US-TST-1-2"), tree) == []

    def test_blocks_via_story(self, tree):
        tree.create_decision("Q?", blocks=["US-TST-1"])
        assert _ids(blocking_decisions(_task(tree, "US-TST-1-1"), tree)) == ["DEC-TST-1"]
        assert _ids(blocking_decisions(_task(tree, "US-TST-1-2"), tree)) == ["DEC-TST-1"]
        assert blocking_decisions(_task(tree, "US-TST-2-1"), tree) == []

    def test_blocks_via_epic(self, tree):
        tree.create_decision("Q?", blocks=["EPIC-TST-1"])
        assert _ids(blocking_decisions(_task(tree, "US-TST-1-1"), tree)) == ["DEC-TST-1"]
        assert _ids(blocking_decisions(_task(tree, "US-TST-1-2"), tree)) == ["DEC-TST-1"]
        assert blocking_decisions(_task(tree, "US-TST-2-1"), tree) == []

    def test_answered_and_withdrawn_never_block(self, tree):
        tree.create_decision("Answered?", blocks=["US-TST-1-1"])
        tree.create_decision("Withdrawn?", blocks=["US-TST-1"])
        tree.create_decision("Still open?", blocks=["EPIC-TST-1"])
        tree.update_decision("DEC-TST-1", status="answered", answer="yes")
        tree.update_decision("DEC-TST-2", status="withdrawn")
        task = _task(tree, "US-TST-1-1")
        assert _ids(blocking_decisions(task, tree)) == ["DEC-TST-3"]
        # The same holds when the caller pre-loads every decision, not just
        # the open ones.
        assert _ids(blocking_decisions(task, tree, **_preloaded(tree))) == ["DEC-TST-3"]

    def test_multiple_decisions_all_returned(self, tree):
        tree.create_decision("By task?", blocks=["US-TST-1-1"])
        tree.create_decision("Unrelated?", blocks=["US-TST-2"])
        tree.create_decision("By epic?", blocks=["EPIC-TST-1"])
        tree.create_decision("By story?", blocks=["US-TST-1", "US-TST-2-1"])
        assert _ids(blocking_decisions(_task(tree, "US-TST-1-1"), tree)) == [
            "DEC-TST-1",
            "DEC-TST-3",
            "DEC-TST-4",
        ]

    def test_task_with_no_epic_link(self, tree):
        # US-TST-2 has no epic: only the task and story ids can match.
        tree.create_decision("Epic?", blocks=["EPIC-TST-1"])
        tree.create_decision("Story?", blocks=["US-TST-2"])
        assert _ids(blocking_decisions(_task(tree, "US-TST-2-1"), tree)) == ["DEC-TST-2"]

    def test_task_whose_story_is_missing(self, tree):
        tree.create_decision("Q?", blocks=["US-TST-1-1"])
        orphan = _task(tree, "US-TST-1-1").model_copy(update={"story_id": "US-TST-99"})
        assert _ids(blocking_decisions(orphan, tree)) == ["DEC-TST-1"]

    def test_no_decisions_at_all(self, tree):
        assert blocking_decisions(_task(tree, "US-TST-1-1"), tree) == []

    def test_preloaded_maps_match_store_path(self, tree):
        tree.create_decision("A?", blocks=["US-TST-1-2"])
        tree.create_decision("B?", blocks=["EPIC-TST-1"])
        tree.create_decision("C?", blocks=["US-TST-2"])
        tree.create_decision("D?", blocks=["US-TST-1"])
        tree.update_decision("DEC-TST-4", status="withdrawn")
        pre = _preloaded(tree)
        for task in tree.list_tasks():
            assert _ids(blocking_decisions(task, tree, **pre)) == _ids(
                blocking_decisions(task, tree)
            ), task.id

    def test_preloaded_path_does_no_store_reads(self, tree, monkeypatch):
        tree.create_decision("Q?", blocks=["EPIC-TST-1"])
        pre = _preloaded(tree)
        task = _task(tree, "US-TST-1-1")

        def boom(*args, **kwargs):
            raise AssertionError("store read on the pre-loaded path")

        monkeypatch.setattr(tree, "list_decisions", boom)
        monkeypatch.setattr(tree, "get_story", boom)
        assert _ids(blocking_decisions(task, tree, **pre)) == ["DEC-TST-1"]

    def test_story_cache_miss_falls_back_to_store(self, tree):
        tree.create_decision("Q?", blocks=["EPIC-TST-1"])
        task = _task(tree, "US-TST-1-1")
        found = blocking_decisions(task, tree, decisions=tree.list_decisions(), stories={})
        assert _ids(found) == ["DEC-TST-1"]

    def test_ordering_is_numeric_not_lexical(self, tree):
        for n in range(1, 12):
            tree.create_decision(f"Q{n}?", blocks=["US-TST-1-1"])
        expected = [f"DEC-TST-{n}" for n in range(1, 12)]
        task = _task(tree, "US-TST-1-1")
        assert _ids(blocking_decisions(task, tree)) == expected
        shuffled = list(reversed(tree.list_decisions()))
        assert _ids(blocking_decisions(task, decisions=shuffled, stories={})) == expected


class TestPureInMemory:
    def _story(self, sid, epic=None):
        return StoryFrontmatter(
            id=sid, title="S", epic_id=epic, created=date.today(), updated=date.today()
        )

    def _decision(self, did, blocks, status="open"):
        extra = {"answer": "x"} if status == "answered" else {}
        return DecisionFrontmatter(
            id=did,
            title="Q?",
            status=status,
            blocks=blocks,
            created=date.today(),
            updated=date.today(),
            **extra,
        )

    def test_no_store_needed_with_maps(self):
        task = TaskFrontmatter(
            id="US-TST-1-1",
            story_id="US-TST-1",
            title="T",
            created=date.today(),
            updated=date.today(),
        )
        stories = {"US-TST-1": self._story("US-TST-1", "EPIC-TST-1")}
        decisions = [
            self._decision("DEC-TST-3", ["EPIC-TST-1"]),
            self._decision("DEC-TST-2", ["US-TST-1"], status="answered"),
            self._decision("DEC-TST-1", ["US-TST-1-1"]),
            self._decision("DEC-TST-4", ["US-TST-1"], status="withdrawn"),
        ]
        found = blocking_decisions(task, decisions=decisions, stories=stories)
        assert _ids(found) == ["DEC-TST-1", "DEC-TST-3"]

    def test_requires_store_or_decisions(self):
        task = TaskFrontmatter(
            id="US-TST-1-1",
            story_id="US-TST-1",
            title="T",
            created=date.today(),
            updated=date.today(),
        )
        with pytest.raises(ValueError):
            blocking_decisions(task)
