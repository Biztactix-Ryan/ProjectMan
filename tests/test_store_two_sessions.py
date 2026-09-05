"""Two sessions on one project never overwrite each other's items.

Criterion under test (US-PM-24):

    Two Store instances on the same project dir create stories in turn and
    both stories survive with distinct IDs.

``tests/test_store.py::TestIdAllocationReconcilesWithDisk`` covers the unit
shape of the fix (``_sync_counters_from_disk`` / ``_highest_numbered``).  This
module is the criterion-level proof: interleaved creates from two live Stores,
the same interleaving through the MCP tool layer, and a mutation test that
disables the fix and shows the collision come straight back — so a future
regression in either helper is caught here and not merely asserted about.
"""

import frontmatter
import pytest
import yaml

from projectman.store import Store, _cache


def _fresh_store(root):
    """A Store that parsed config.yaml for itself, the way a new process would.

    ``config.load_config`` memoises per root, so without dropping that cache
    both Stores would share one ``ProjectConfig`` object and a counter bump in
    one would be visible in the other for the wrong reason.
    """
    from projectman.config import clear_config_cache

    clear_config_cache()
    _cache.clear()
    return Store(root)


def _num(item_id: str) -> int:
    """The trailing number of a story/epic ID (``US-TST-12`` -> 12)."""
    return int(item_id.rsplit("-", 1)[1])


def _assert_intact(path, expected_id, expected_title):
    """The file exists, its frontmatter id matches its name, and it kept its title."""
    assert path.exists(), f"{path.name} was removed or never written"
    post = frontmatter.load(str(path))
    assert post.metadata["id"] == expected_id
    assert path.stem == expected_id, "filename and frontmatter id must agree"
    assert post.metadata["title"] == expected_title, (
        f"{path.name} was overwritten: expected title {expected_title!r}, "
        f"found {post.metadata['title']!r}"
    )


class TestTwoStoreSessions:
    """Two Store objects on one project dir, each with its own caches."""

    def test_interleaved_story_creates_all_survive(self, tmp_project):
        """A creates, B creates, A creates again: three distinct, intact stories."""
        store_a = _fresh_store(tmp_project)
        store_b = _fresh_store(tmp_project)
        assert store_a is not store_b
        assert store_a.config is not store_b.config, (
            "the two Stores must hold independent config snapshots, "
            "otherwise this models one session and proves nothing"
        )

        first, _ = store_a.create_story("Alpha from A", "Body alpha")
        second, _ = store_b.create_story("Beta from B", "Body beta")
        third, _ = store_a.create_story("Gamma from A", "Body gamma")

        ids = [first.id, second.id, third.id]
        assert len(set(ids)) == 3, f"IDs were reused: {ids}"
        nums = [_num(i) for i in ids]
        assert nums == sorted(nums), f"IDs must increase in creation order: {ids}"
        assert nums == [1, 2, 3]

        stories_dir = tmp_project / ".project" / "stories"
        on_disk = sorted(p.name for p in stories_dir.glob("US-TST-*.md"))
        assert len(on_disk) == 3, f"expected three story files, found {on_disk}"

        _assert_intact(stories_dir / f"{first.id}.md", first.id, "Alpha from A")
        _assert_intact(stories_dir / f"{second.id}.md", second.id, "Beta from B")
        _assert_intact(stories_dir / f"{third.id}.md", third.id, "Gamma from A")

        for meta, body in ((first, "Body alpha"), (second, "Body beta"), (third, "Body gamma")):
            assert body in (stories_dir / f"{meta.id}.md").read_text()

    def test_interleaved_epic_creates_all_survive(self, tmp_project):
        """Same interleaving for epics, which allocate through ``_next_epic_id``."""
        store_a = _fresh_store(tmp_project)
        store_b = _fresh_store(tmp_project)
        assert store_a.config is not store_b.config

        first = store_a.create_epic("Epic Alpha from A", "Body alpha")
        second = store_b.create_epic("Epic Beta from B", "Body beta")
        third = store_a.create_epic("Epic Gamma from A", "Body gamma")

        ids = [first.id, second.id, third.id]
        assert len(set(ids)) == 3, f"IDs were reused: {ids}"
        nums = [_num(i) for i in ids]
        assert nums == sorted(nums), f"IDs must increase in creation order: {ids}"
        assert nums == [1, 2, 3]

        epics_dir = tmp_project / ".project" / "epics"
        on_disk = sorted(p.name for p in epics_dir.glob("EPIC-TST-*.md"))
        assert len(on_disk) == 3, f"expected three epic files, found {on_disk}"

        _assert_intact(epics_dir / f"{first.id}.md", first.id, "Epic Alpha from A")
        _assert_intact(epics_dir / f"{second.id}.md", second.id, "Epic Beta from B")
        _assert_intact(epics_dir / f"{third.id}.md", third.id, "Epic Gamma from A")


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


class TestToolLevel:
    """The criterion through ``pm_create_story`` rather than ``Store`` directly."""

    def test_server_shares_one_store_per_root(self, server_project):
        """Documented constraint: the tool layer cannot give us two Stores.

        ``server._store()`` memoises one Store per ``.project`` directory in
        ``_store_cache`` for the life of the process, so every tool call in a
        process reuses one instance and one set of caches.  Two *sessions* are
        therefore two processes, which a single test process cannot host
        through the tool API — hence the simulation in the next test, where the
        other session's effect (a file on disk whose number this process's
        counter has not been told about) is reproduced directly.
        """
        from projectman.server import _store

        assert _store() is _store()

    def test_pm_create_story_skips_past_another_sessions_file(self, server_project):
        """A story another session wrote is never overwritten by the next create."""
        from projectman.server import pm_create_story

        first = yaml.safe_load(
            pm_create_story("Alpha from session one", "Body alpha")
        )["created"]["id"]
        assert first == "US-TST-1"

        # What a second session leaves behind: the next file on disk, without
        # this process's in-memory counter ever hearing about it (a git pull of
        # a teammate's story looks exactly the same).
        stories_dir = server_project / ".project" / "stories"
        other = stories_dir / "US-TST-2.md"
        other.write_text(
            "---\nid: US-TST-2\ntitle: Beta from session two\nstatus: backlog\n"
            "---\nBody beta\n"
        )

        third = yaml.safe_load(
            pm_create_story("Gamma from session one", "Body gamma")
        )["created"]["id"]

        assert third == "US-TST-3", f"create landed on {third}, not past the other session"

        _assert_intact(stories_dir / "US-TST-1.md", "US-TST-1", "Alpha from session one")
        _assert_intact(other, "US-TST-2", "Beta from session two")
        _assert_intact(stories_dir / "US-TST-3.md", "US-TST-3", "Gamma from session one")
        assert len(list(stories_dir.glob("US-TST-*.md"))) == 3


class TestMutationProvesTheFixIsLoadBearing:
    """Disable the reconciliation and the collision must come back.

    Without this, the tests above would still pass against a Store that
    reconciled by accident (a shared config object, a lucky cache).  Both
    helpers are neutered together because either one alone still corrects the
    counter: ``_sync_counters_from_disk`` re-reads config.yaml, and
    ``_highest_numbered`` finds the file even when no counter moved.
    ``monkeypatch`` restores both on teardown.
    """

    @staticmethod
    def _disable_reconciliation(monkeypatch):
        monkeypatch.setattr(Store, "_sync_counters_from_disk", lambda self: None)
        # _highest_numbered is a staticmethod; it must stay one or `self`
        # would be bound into the first parameter.
        monkeypatch.setattr(
            Store, "_highest_numbered", staticmethod(lambda directory, id_prefix: 0)
        )

    def test_two_sessions_collide_without_the_fix(self, tmp_project, monkeypatch):
        """Both Stores hand out ``US-TST-1``; the write guard stops the clobber.

        Before US-PM-24-7 the second ``create_story`` overwrote the first and
        A's title was simply gone.  The reconciliation is still what keeps the
        collision from arising — this mutation proves it, because disabling it
        makes both Stores mint the same ID — but the create is now also its own
        last line of defence: an ID that is already on disk is refused, so the
        worst case is a raised error rather than lost work.
        """
        self._disable_reconciliation(monkeypatch)

        store_a = _fresh_store(tmp_project)
        store_b = _fresh_store(tmp_project)

        first, _ = store_a.create_story("Alpha from A", "Body alpha")

        with pytest.raises(FileExistsError, match="US-TST-1 already exists"):
            store_b.create_story("Beta from B", "Body beta")

        assert first.id == "US-TST-1", (
            "with the reconciliation disabled both Stores must hand out the same ID; "
            "if they do not, this mutation no longer exercises the fix"
        )

        stories_dir = tmp_project / ".project" / "stories"
        survivors = sorted(p.name for p in stories_dir.glob("US-TST-*.md"))
        assert survivors == ["US-TST-1.md"], f"expected one file, found {survivors}"

        text = (stories_dir / "US-TST-1.md").read_text()
        assert "Alpha from A" in text, "the overwrite this criterion forbids happened"
        assert "Beta from B" not in text

    def test_epics_collide_without_the_fix(self, tmp_project, monkeypatch):
        """Same mutation, same collision on the epic path, same refusal."""
        self._disable_reconciliation(monkeypatch)

        store_a = _fresh_store(tmp_project)
        store_b = _fresh_store(tmp_project)

        first = store_a.create_epic("Epic Alpha from A", "Body alpha")

        with pytest.raises(FileExistsError, match="EPIC-TST-1 already exists"):
            store_b.create_epic("Epic Beta from B", "Body beta")

        assert first.id == "EPIC-TST-1"

        epics_dir = tmp_project / ".project" / "epics"
        survivors = sorted(p.name for p in epics_dir.glob("EPIC-TST-*.md"))
        assert survivors == ["EPIC-TST-1.md"]
        assert "Epic Alpha from A" in (epics_dir / "EPIC-TST-1.md").read_text()

    def test_reconciliation_is_restored_after_the_mutation(self, tmp_project):
        """Guard: monkeypatch teardown put the real helpers back.

        A leaked no-op would silently defeat every later test in the run, so
        the restoration is asserted rather than assumed.
        """
        store = _fresh_store(tmp_project)
        stories_dir = tmp_project / ".project" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "US-TST-9.md").write_text("---\nid: US-TST-9\n---\nPulled\n")

        assert Store._highest_numbered(stories_dir, "US-TST-") == 9
        meta, _ = store.create_story("After restore", "Body")
        assert meta.id == "US-TST-10"
