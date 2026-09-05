"""A removed task file never lets the next create land on a survivor.

Criterion under test (US-PM-24):

    Removing a task file and then creating a task yields an ID higher than
    every surviving task.

``tests/test_store.py::TestTaskIdAllocationScansDisk`` covers the unit shape of
the allocator (``_highest_numbered`` plus ``_task_high_water``).  This module
is the criterion-level proof: the same sequence through the MCP tool layer, the
same sequence seen by a *new session* whose only knowledge is the directory
listing, the archived-task variant (archiving is a status change, so the file
stays and its number must stay taken), and a mutation test that blinds the disk
scan and shows the collision come straight back — so a regression in the
allocator is caught here rather than merely asserted about.
"""

import frontmatter
import pytest
import yaml

from projectman.store import Store, _cache


def _fresh_store(root):
    """A Store that parsed config.yaml for itself, the way a new process would.

    ``config.load_config`` memoises per root and ``_cache`` memoises parsed
    items, so both are dropped: a "second session" that inherited this
    process's caches would prove nothing about what a cold start sees on disk.
    Crucially the new Store also starts with an empty ``_task_high_water``, so
    its allocation rests on the directory scan alone.
    """
    from projectman.config import clear_config_cache

    clear_config_cache()
    _cache.clear()
    return Store(root)


def _suffix(task_id: str) -> int:
    """The task number of a task ID (``US-TST-1-12`` -> 12)."""
    return int(task_id.rsplit("-", 1)[1])


def _tasks_dir(root):
    return root / ".project" / "tasks"


def _survivors(root, story_id: str) -> dict:
    """``{path: bytes}`` for every task file of *story_id* now on disk."""
    return {
        p: p.read_bytes()
        for p in sorted(_tasks_dir(root).glob(f"{story_id}-*.md"))
    }


def _assert_unchanged(before: dict) -> None:
    """Every file snapshotted in *before* still exists with identical bytes."""
    for path, blob in before.items():
        assert path.exists(), f"{path.name} disappeared during the create"
        assert path.read_bytes() == blob, (
            f"{path.name} was overwritten by the create: its bytes changed"
        )


def _assert_above_survivors(new_id: str, before: dict) -> None:
    """*new_id* numbers above every file that was on disk before the create."""
    highest = max((_suffix(p.stem) for p in before), default=0)
    assert _suffix(new_id) > highest, (
        f"{new_id} did not clear the surviving tasks "
        f"{sorted(p.stem for p in before)} (highest suffix {highest})"
    )


@pytest.fixture
def server_project(tmp_project, monkeypatch):
    """Point the MCP server's tools at *tmp_project* and hand back its root.

    ``PROJECTMAN_ROOT`` wins over cwd in ``find_project_root``, so it is
    removed here: with it left set from the ambient environment a server tool
    would write to a real project instead of the tmp one.  The assert is the
    guard rail, not decoration.
    """
    from projectman.config import find_project_root
    from projectman.server import _store_cache

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    _store_cache.clear()
    _cache.clear()
    assert find_project_root() == tmp_project.resolve()
    yield tmp_project
    _store_cache.clear()


def _seed_story_and_tasks(root, titles=("One", "Two", "Three")) -> list[str]:
    """Create ``US-TST-1`` and its tasks through the MCP tools; return the IDs."""
    from projectman.server import pm_create_story, pm_create_tasks

    story = yaml.safe_load(pm_create_story("Story", "Story body"))["created"]["id"]
    assert story == "US-TST-1"
    created = yaml.safe_load(
        pm_create_tasks(
            story,
            [{"title": t, "description": f"Desc {t}"} for t in titles],
        )
    )["created"]
    return [entry["id"] for entry in created]


class TestToolLevel:
    """The criterion through ``pm_create_task``, not ``Store`` directly."""

    def test_create_after_removing_the_middle_task_clears_every_survivor(
        self, server_project
    ):
        """Delete ``-2`` of three and the next create must not rewrite ``-3``.

        This is the exact shape of the original bug: ``len(tasks) + 1`` was 3
        once the middle file was gone, so the create reused ``-3`` and the
        surviving task's body was replaced in place with no error.
        """
        from projectman.server import pm_create_task

        ids = _seed_story_and_tasks(server_project)
        assert ids == ["US-TST-1-1", "US-TST-1-2", "US-TST-1-3"]

        removed = _tasks_dir(server_project) / "US-TST-1-2.md"
        removed.unlink()
        before = _survivors(server_project, "US-TST-1")
        assert sorted(p.stem for p in before) == ["US-TST-1-1", "US-TST-1-3"]

        new_id = yaml.safe_load(
            pm_create_task("US-TST-1", "Four", "Desc Four")
        )["created"]["id"]

        _assert_above_survivors(new_id, before)
        _assert_unchanged(before)
        assert not removed.exists(), "the deleted task was resurrected"

        written = _tasks_dir(server_project) / f"{new_id}.md"
        post = frontmatter.load(str(written))
        assert post.metadata["id"] == new_id
        assert post.metadata["title"] == "Four"
        assert post.metadata["story_id"] == "US-TST-1"


class TestANewSessionSeesOnlyTheDisk:
    """A cold Store has no memory of handed-out numbers — only the listing."""

    def test_fresh_store_after_removal_still_allocates_above_survivors(
        self, server_project
    ):
        """The next session's create clears the survivors on the scan alone.

        The tool-level test above is also protected by ``_task_high_water``,
        which remembers this process's allocations.  A new session has none of
        that, so this is the case where ``_highest_numbered`` is the only thing
        standing between the create and a live file.
        """
        _seed_story_and_tasks(server_project)
        (_tasks_dir(server_project) / "US-TST-1-2.md").unlink()

        store = _fresh_store(server_project)
        assert store._task_high_water == {}, (
            "a simulated new session must start with no allocation memory, "
            "otherwise the disk scan is not what is being tested"
        )
        before = _survivors(server_project, "US-TST-1")

        meta = store.create_task("US-TST-1", "Four", "Desc Four")

        _assert_above_survivors(meta.id, before)
        _assert_unchanged(before)
        assert meta.id == "US-TST-1-4"


class TestArchivedTasksKeepTheirNumbers:
    """Archiving a task is a status change: the file — and its ID — stay put."""

    def test_removed_top_plus_archived_task_still_yields_a_clear_id(
        self, server_project
    ):
        """Never reuse the archived task's number, in this session or the next.

        Tasks are archived by an ``archived`` flag, not by moving the file, so
        the tasks dir remains the whole population and one scan covers it.  The
        arrangement here is chosen to bite: with ``-4`` deleted and ``-3``
        archived, an allocator that counted only live, unarchived tasks would
        hand out ``-3`` and overwrite the archived one.
        """
        from projectman.server import _store

        _seed_story_and_tasks(server_project, titles=("One", "Two", "Three", "Four"))
        store = _store()
        store.archive("US-TST-1-3")

        archived_path = _tasks_dir(server_project) / "US-TST-1-3.md"
        assert archived_path.exists(), "archiving a task must not move its file"
        assert frontmatter.load(str(archived_path)).metadata["archived"] is True

        (_tasks_dir(server_project) / "US-TST-1-4.md").unlink()
        before = _survivors(server_project, "US-TST-1")
        assert sorted(p.stem for p in before) == [
            "US-TST-1-1",
            "US-TST-1-2",
            "US-TST-1-3",
        ]

        same_session = store.create_task("US-TST-1", "Five", "Desc Five").id
        _assert_above_survivors(same_session, before)
        assert same_session != "US-TST-1-3", "the archived task's ID was reused"
        _assert_unchanged(before)

        after_first = _survivors(server_project, "US-TST-1")
        next_session = _fresh_store(server_project).create_task(
            "US-TST-1", "Six", "Desc Six"
        ).id
        _assert_above_survivors(next_session, after_first)
        assert next_session != "US-TST-1-3"
        assert next_session != same_session
        _assert_unchanged(after_first)

        assert frontmatter.load(str(archived_path)).metadata["title"] == "Three"


class TestMutationProvesTheScanIsLoadBearing:
    """Blind the disk scan and the create must stop clearing the survivors.

    Without this the tests above would pass against an allocator that cleared
    the survivors by luck (a counter that happened to be ahead, a cache that
    happened to be warm).  ``_highest_numbered`` is stubbed to 0 — the answer a
    scan that cannot see the directory would give — and the allocation falls
    back to the low numbers the old ``len + 1`` code produced.  What is then
    asserted is the consequence: the create targets a number a live file
    already owns, US-PM-24-7's exists check refuses it, and no bytes move.
    ``monkeypatch`` restores the real method on teardown.
    """

    @staticmethod
    def _blind_the_scan(monkeypatch):
        # _highest_numbered is a staticmethod; it must stay one or `self`
        # would be bound into the first parameter.
        monkeypatch.setattr(
            Store, "_highest_numbered", staticmethod(lambda directory, id_prefix: 0)
        )

    def test_without_the_scan_the_create_collides_and_loses_nothing(
        self, server_project, monkeypatch
    ):
        """A blinded allocator hands out a taken number; the guard catches it."""
        _seed_story_and_tasks(server_project)
        (_tasks_dir(server_project) / "US-TST-1-2.md").unlink()
        before = _survivors(server_project, "US-TST-1")

        self._blind_the_scan(monkeypatch)
        # A new session, so _task_high_water cannot stand in for the scan.
        store = _fresh_store(server_project)
        assert store._next_task_id("US-TST-1") == "US-TST-1-1", (
            "with the scan blinded the allocator must fall back to a low, "
            "already-taken number — otherwise this mutation proves nothing"
        )

        broken = _fresh_store(server_project)
        with pytest.raises(FileExistsError, match="US-TST-1-1 already exists"):
            broken.create_task("US-TST-1", "Four", "Desc Four")

        _assert_unchanged(before)

        # And with the real scan back, the same create clears the survivors.
        monkeypatch.undo()
        repaired = _fresh_store(server_project)
        meta = repaired.create_task("US-TST-1", "Four", "Desc Four")
        _assert_above_survivors(meta.id, before)
        _assert_unchanged(before)
