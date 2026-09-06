"""Every create writes atomically, through ``_atomic_write_text`` (US-PM-24).

Criterion under verification:

    Item creates write atomically via ``_atomic_write_text``.

``tests/test_store.py::TestCreatesWriteAtomically`` covers the individual
methods US-PM-24-7 touched.  This module is the *criterion-level* proof, and
it is built so it cannot quietly go out of date:

* :class:`TestEveryCreateUsesTheAtomicHelper` reflects over ``Store`` with
  :mod:`inspect` — every ``create_*`` method that exists at run time must call
  ``_atomic_write_text`` and must not call ``.write_text``, so a future create
  method (or a refactor back to a plain write) fails here without anyone
  having to remember to extend a list.  ``server.pm_fix_malformed``, the one
  create-shaped path outside ``Store``, is held to the same rule.
* :class:`TestATornCreateNeverBecomesAnItem` kills every create path *inside*
  the helper — after the temp file is fully written, at the ``os.replace``
  that is supposed to be the only visible moment — and asserts the target
  never appeared and no temp debris was left behind.
* :class:`TestAConcurrentReaderNeverSeesAPartialItem` is the guarantee stated
  positively: a reader hammering the directory while 50 items are created
  must only ever see whole files.  The bodies are deliberately ~64 KiB, well
  past a single ``write`` of the page cache buffer, so a non-atomic write
  really would be observable as a torn read rather than being hidden by
  buffering.
* :class:`TestCreatedFilesAreNotOwnerOnly` pins the mode fix that came with
  the helper: ``mkstemp`` creates 0600, so an item created through it must be
  re-chmodded or created items would be more private than hand-written ones.

The cleanup behaviour is *pinned*, not assumed: ``_atomic_write_text`` unlinks
its own temp file in a ``except BaseException`` block, so a failed create
leaves the directory exactly as it found it — no ``.<name>.*.tmp`` debris.
That is what these tests assert; if the helper is ever changed to leave debris
behind, these tests are where that decision gets re-made.
"""

import inspect
import os
import threading

import frontmatter
import pytest

from projectman.store import Store, _cache
import projectman.store as store_module


# ─── helpers ─────────────────────────────────────────────────────────


def _proj(tmp_project):
    """The .project dir with every item subdirectory present."""
    proj = tmp_project / ".project"
    for sub in ("stories", "tasks", "epics", "sprints"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    return proj


def _debris(directory):
    """Leftover temp files from :func:`_atomic_write_text` in *directory*."""
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def _create_methods():
    """Every ``create_*`` method that exists on ``Store`` right now."""
    return sorted(n for n in dir(Store) if n.startswith("create_"))


# ─── (1) the static proof ────────────────────────────────────────────


class TestEveryCreateUsesTheAtomicHelper:
    """Reflection over the real code, so a new create path cannot slip past."""

    def test_the_enumeration_is_not_empty(self):
        """Guard the guard: a broken reflection must not pass vacuously."""
        names = _create_methods()
        assert len(names) >= 5, names
        assert {
            "create_story",
            "create_task",
            "create_tasks",
            "create_epic",
            "create_sprint",
        } <= set(names)

    @pytest.mark.parametrize("name", _create_methods())
    def test_store_create_writes_through_the_helper(self, name):
        src = inspect.getsource(getattr(Store, name))
        assert "_atomic_write_text(" in src, (
            f"Store.{name} does not write through _atomic_write_text"
        )
        assert ".write_text(" not in src, (
            f"Store.{name} writes with a plain .write_text — a crash mid-write "
            f"leaves a truncated item on disk"
        )

    def test_pm_fix_malformed_writes_through_the_helper(self):
        """The one create-shaped path outside ``Store.create_*``."""
        from projectman import server as srv

        src = inspect.getsource(srv.pm_fix_malformed)
        assert "_atomic_write_text(" in src
        assert ".write_text(" not in src

    def test_the_helper_actually_is_atomic(self):
        """``_atomic_write_text`` is a same-dir temp file plus ``os.replace``.

        The tests above only prove the creates *call* the helper.  This one
        pins what the helper does, so the criterion cannot be satisfied by a
        helper that has quietly become a plain write.
        """
        src = inspect.getsource(store_module._atomic_write_text)
        assert "mkstemp(" in src
        assert "dir=str(path.parent)" in src, (
            "the temp file must live in the target's own directory or the "
            "rename can cross filesystems and stop being atomic"
        )
        assert "os.replace(tmp_name, path)" in src
        assert "os.unlink(tmp_name)" in src, "the helper must clean up its own temp file"


# ─── (2) a torn create never becomes an item ─────────────────────────


def _case_story(store, proj):
    return (
        proj / "stories",
        proj / "stories" / "US-TST-1.md",
        lambda: store.create_story("Doomed", "Body"),
    )


def _case_task(store, proj):
    store.create_story("Story", "Desc")
    return (
        proj / "tasks",
        proj / "tasks" / "US-TST-1-1.md",
        lambda: store.create_task("US-TST-1", "Doomed", "Body"),
    )


def _case_tasks(store, proj):
    store.create_story("Story", "Desc")
    return (
        proj / "tasks",
        proj / "tasks" / "US-TST-1-1.md",
        lambda: store.create_tasks(
            "US-TST-1",
            [{"title": "A", "description": "A"}, {"title": "B", "description": "B"}],
        ),
    )


def _case_epic(store, proj):
    return (
        proj / "epics",
        proj / "epics" / "EPIC-TST-1.md",
        lambda: store.create_epic("Doomed", "Body"),
    )


def _case_sprint(store, proj):
    return (
        proj / "sprints",
        proj / "sprints" / "SPRINT-TST-1.md",
        lambda: store.create_sprint("Doomed"),
    )


CASES = {
    "create_story": _case_story,
    "create_task": _case_task,
    "create_tasks": _case_tasks,
    "create_epic": _case_epic,
    "create_sprint": _case_sprint,
}


class TestATornCreateNeverBecomesAnItem:
    """Kill each create inside the helper, after the temp file is written.

    ``os.replace`` is the single instant at which a create becomes visible.
    Failing exactly there is the worst case the helper claims to survive: the
    content exists, complete, in a temp file, and the move into place never
    happens.  The target must not exist afterwards, and — pinning the helper's
    ``except BaseException`` cleanup — no ``.<name>.*.tmp`` debris may remain.
    """

    @staticmethod
    def _break_replace(monkeypatch, observed):
        """Fail ``os.replace``, recording that the temp file was complete."""
        def fail_replace(src, dst):
            observed.append((str(src), os.path.exists(src), os.path.getsize(src)))
            raise OSError("power cut before rename")

        monkeypatch.setattr(store_module.os, "replace", fail_replace)

    def test_the_enumeration_is_complete(self):
        """Every ``Store.create_*`` has a behavioural case below."""
        assert set(CASES) == set(_create_methods()), (
            "a create method was added or renamed without a torn-write case"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_target_never_appears_and_no_debris_is_left(
        self, name, store, tmp_project, monkeypatch
    ):
        proj = _proj(tmp_project)
        directory, target, action = CASES[name](store, proj)
        before = sorted(p.name for p in directory.iterdir())
        assert not target.exists()

        observed = []
        self._break_replace(monkeypatch, observed)

        with pytest.raises(OSError, match="power cut before rename"):
            action()

        monkeypatch.undo()

        # The failure really was mid-write, not before it: the helper had
        # already written a complete temp file when it died.
        assert observed, f"{name} never reached os.replace — it did not write atomically"
        tmp_name, existed, size = observed[0]
        assert existed and size > 0, "the temp file was not written before the rename"
        assert not os.path.exists(tmp_name), "the temp file outlived the failed create"

        assert not target.exists(), f"{name} left a partial item at {target}"
        assert _debris(directory) == [], "the failed create left temp-file debris"
        assert sorted(p.name for p in directory.iterdir()) == before, (
            "the failed create changed the directory"
        )

    def test_pm_fix_malformed_target_never_appears(self, server_project, monkeypatch):
        from projectman import server as srv
        from mcp.server.fastmcp.exceptions import ToolError

        store = srv._store()
        proj = _proj(server_project)
        stories = proj / "stories"
        malformed = proj / "malformed"
        malformed.mkdir(parents=True, exist_ok=True)
        source = malformed / "broken.md"
        source.write_text("no frontmatter here, just prose\n")
        before = sorted(p.name for p in stories.iterdir())

        observed = []
        self._break_replace(monkeypatch, observed)

        with pytest.raises((OSError, ToolError)):
            srv.pm_fix_malformed(
                filename="broken.md", id="US-TST-9", title="Fixed", item_type="story"
            )

        monkeypatch.undo()

        assert observed, "pm_fix_malformed never reached os.replace"
        assert not (stories / "US-TST-9.md").exists()
        assert _debris(stories) == []
        assert sorted(p.name for p in stories.iterdir()) == before
        assert source.exists(), "the failed fix consumed the quarantined file"


# ─── (3) a concurrent reader only ever sees whole items ──────────────


class TestAConcurrentReaderNeverSeesAPartialItem:
    """The guarantee stated positively, with a real reader thread."""

    N = 50
    #: ~64 KiB — larger than any single buffered write, so a non-atomic
    #: create would genuinely be observable half-written.
    FILLER = "filler line for the atomicity test\n" * 1800

    def _body(self, i):
        return f"START-{i}\n{self.FILLER}END-{i}\n"

    def test_every_read_during_50_creates_parses_whole(self, store, tmp_project):
        proj = _proj(tmp_project)
        tasks = proj / "tasks"
        store.create_story("Story", "Desc")

        failures = []
        reads = [0]
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    paths = sorted(tasks.glob("*.md"))
                except OSError:
                    continue
                for path in paths:
                    try:
                        text = path.read_text()
                    except FileNotFoundError:
                        continue
                    except OSError as exc:  # pragma: no cover - environment
                        failures.append(f"{path.name}: {exc!r}")
                        continue
                    stem = path.stem
                    if not text:
                        failures.append(f"{path.name}: read back empty")
                        continue
                    try:
                        post = frontmatter.loads(text)
                    except Exception as exc:
                        failures.append(f"{path.name}: unparseable ({exc!r})")
                        continue
                    if post.metadata.get("id") != stem:
                        failures.append(
                            f"{path.name}: id {post.metadata.get('id')!r} != {stem!r}"
                        )
                        continue
                    index = stem.rsplit("-", 1)[1]
                    if f"START-{index}" not in post.content:
                        failures.append(f"{path.name}: body head missing")
                    elif not post.content.rstrip().endswith(f"END-{index}"):
                        failures.append(f"{path.name}: body truncated")
                    else:
                        reads[0] += 1

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            for i in range(1, self.N + 1):
                store.create_task("US-TST-1", f"Task {i}", self._body(i))
        finally:
            stop.set()
            thread.join(timeout=30)

        assert not thread.is_alive()
        assert failures == [], failures[:5]
        assert len(list(tasks.glob("*.md"))) == self.N
        # Not vacuous: the reader really did observe files mid-run.
        assert reads[0] > self.N, reads[0]

    def test_a_torn_write_would_have_been_caught(self, store, tmp_project):
        """Falsification check: the reader's assertions do detect a torn file.

        Without this, a reader that never actually inspected anything would
        pass the test above for the wrong reason.
        """
        proj = _proj(tmp_project)
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task 1", self._body(1))
        path = proj / "tasks" / "US-TST-1-1.md"
        whole = path.read_text()

        post = frontmatter.loads(whole)
        assert post.metadata["id"] == "US-TST-1-1"
        assert post.content.rstrip().endswith("END-1")

        truncated = frontmatter.loads(whole[: len(whole) // 2])
        assert not truncated.content.rstrip().endswith("END-1")


# ─── (4) created files are not owner-only ────────────────────────────


class TestCreatedFilesAreNotOwnerOnly:
    """``mkstemp`` makes 0600 files; a created item must not inherit that."""

    @staticmethod
    def _mode(path):
        return path.stat().st_mode & 0o777

    def test_created_story_matches_a_hand_written_file(self, store, tmp_project):
        proj = _proj(tmp_project)
        control = proj / "stories" / "control.txt"
        with open(control, "w") as fh:
            fh.write("hand-written\n")

        store.create_story("Story", "Desc")
        created = proj / "stories" / "US-TST-1.md"

        assert self._mode(created) == self._mode(control), (
            "a created item is not as readable as a file written with open()"
        )

    @pytest.mark.parametrize(
        "name",
        ["create_story", "create_task", "create_tasks", "create_epic", "create_sprint"],
    )
    def test_created_files_are_not_owner_only(self, name, store, tmp_project):
        proj = _proj(tmp_project)
        control = proj / "control.txt"
        with open(control, "w") as fh:
            fh.write("hand-written\n")
        if self._mode(control) == 0o600:  # pragma: no cover - exotic umask
            pytest.skip("umask makes even a plain open() file owner-only")

        _, target, action = CASES[name](store, proj)
        action()

        assert target.exists()
        assert self._mode(target) != 0o600, f"{name} left the mkstemp 0600 mode in place"
        assert self._mode(target) == self._mode(control)


# ─── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def server_project(tmp_project, monkeypatch):
    """Point the MCP tools at *tmp_project*, with a guard rail.

    ``PROJECTMAN_ROOT`` beats cwd in ``find_project_root``, so an ambient
    value would send these writes at a real project.  It is removed and the
    resolution asserted before any tool runs.
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
