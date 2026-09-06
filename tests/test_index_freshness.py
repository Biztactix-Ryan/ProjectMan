"""``indexer.ensure_fresh`` — a reader's guard against a lagging index.

Pins the last unmet half of story US-PM-29 ("A write leaves only the item
file and the activity log dirty"): once the mutating tools stopped rebuilding
the five derived index files after every write, whatever still *reads* those
files had to learn to notice when they had fallen behind.

``ensure_fresh(store)`` is that check.  It compares ``index.yaml``'s mtime
against the newest file under ``epics/``, ``stories/`` and ``tasks/`` and
rebuilds only when the items have moved on, so it is cheap enough to sit on a
read path and honest enough that no reader serves stale counts.

Every timestamp here is set explicitly with ``os.utime``: a test that slept
and hoped would be at the mercy of the filesystem's mtime granularity, and
the property under test is precisely an ordering of timestamps.
"""

import os
from pathlib import Path

import yaml

from projectman.indexer import ensure_fresh, index_is_stale, write_index
from projectman.store import Store

INDEX_FILES = (
    "index.yaml",
    "INDEX.md",
    "INDEX-EPICS.md",
    "INDEX-STORIES.md",
    "INDEX-TASKS.md",
)

STORY_BODY = "As a developer I want readers to notice a lagging index.\n"
TASK_BODY = (
    "## Implementation\n\nDo the thing.\n\n"
    "## Testing\n\nTest the thing.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


# ─── Helpers ──────────────────────────────────────────────────────


def _index_path(store: Store) -> Path:
    return store.project_dir / "index.yaml"


def _index_data(store: Store) -> dict:
    return yaml.safe_load(_index_path(store).read_text())


def _entry(index: dict, item_id: str) -> dict:
    for entry in index["entries"]:
        if entry["id"] == item_id:
            return entry
    raise AssertionError(f"{item_id} missing from index entries")


def _newest_item_mtime_ns(store: Store) -> int:
    """The newest item mtime, in whole nanoseconds.

    Nanoseconds, not ``st_mtime`` seconds: a float carries ~15 significant
    digits, which is not enough to hold a nanosecond-resolution epoch
    timestamp exactly.  Reading a time as a float and writing it back rounds
    it, and the rounding is invisible until a test asserts that two
    timestamps are *equal* — which is exactly what
    ``test_an_index_written_at_the_same_instant_is_fresh`` does against
    ``index_is_stale``'s strict ``st_mtime_ns`` comparison.
    """
    mtimes = [
        p.stat().st_mtime_ns
        for directory in (store.epics_dir, store.stories_dir, store.tasks_dir)
        if directory.is_dir()
        for p in directory.glob("*.md")
    ]
    assert mtimes, "fixture should have written at least one item file"
    return max(mtimes)


def _set_mtime_ns(path: Path, when_ns: int) -> None:
    os.utime(path, ns=(when_ns, when_ns))


def _age_index(store: Store, seconds: float = 10.0) -> None:
    """Backdate ``index.yaml`` behind the newest item file."""
    _set_mtime_ns(
        _index_path(store), _newest_item_mtime_ns(store) - int(seconds * 1_000_000_000)
    )


def _freshen_index(store: Store, seconds: float = 10.0) -> None:
    """Postdate ``index.yaml`` ahead of every item file."""
    _set_mtime_ns(
        _index_path(store), _newest_item_mtime_ns(store) + int(seconds * 1_000_000_000)
    )


def _seeded(store: Store) -> tuple[str, str]:
    """A story, a task, and a written index — the state between rebuilds."""
    story, _ = store.create_story("Freshness", STORY_BODY)
    task = store.create_task(story.id, "A task", TASK_BODY)
    write_index(store)
    return story.id, task.id


# ─── Staleness detection ──────────────────────────────────────────


def test_a_missing_index_is_stale(store):
    _seeded(store)
    _index_path(store).unlink()

    assert index_is_stale(store) is True


def test_an_index_older_than_an_item_is_stale(store):
    _seeded(store)
    _age_index(store)

    assert index_is_stale(store) is True


def test_an_index_newer_than_every_item_is_fresh(store):
    _seeded(store)
    _freshen_index(store)

    assert index_is_stale(store) is False


def test_an_index_written_at_the_same_instant_is_fresh(store):
    """Equality means "written together", not "behind".

    ``write_index`` writes ``index.yaml`` after reading the item files, so on
    a coarse-grained filesystem the two can share a timestamp.  Treating that
    as stale would make every read rebuild forever — the churn this story
    exists to remove.
    """
    _seeded(store)
    _set_mtime_ns(_index_path(store), _newest_item_mtime_ns(store))

    assert index_is_stale(store) is False


def test_a_project_with_no_items_is_never_stale(store):
    """Nothing can have outrun an index built from nothing."""
    write_index(store)
    _set_mtime_ns(_index_path(store), 0)

    assert index_is_stale(store) is False


# ─── ensure_fresh ─────────────────────────────────────────────────


def test_ensure_fresh_rebuilds_a_missing_index(store):
    story_id, _task_id = _seeded(store)
    for name in INDEX_FILES:
        (store.project_dir / name).unlink()

    assert ensure_fresh(store) is True

    assert [n for n in INDEX_FILES if not (store.project_dir / n).exists()] == []
    assert _entry(_index_data(store), story_id)["title"] == "Freshness"


def test_ensure_fresh_rebuilds_an_index_left_behind_by_a_write(store):
    """The story's criterion, at the unit: a write that skipped reindexing.

    The task is updated through the Store — which, since US-PM-29, rewrites
    the task file and nothing else — so the on-disk index still says "todo"
    until a reader asks for freshness.
    """
    _story_id, task_id = _seeded(store)
    store.update(task_id, status="in-progress")
    _age_index(store)
    assert _entry(_index_data(store), task_id)["status"] == "todo"

    assert ensure_fresh(store) is True

    assert _entry(_index_data(store), task_id)["status"] == "in-progress"


def test_ensure_fresh_writes_nothing_when_the_index_is_current(store):
    """Cheap on the read path: a fresh index is not rewritten.

    Asserted on mtime as well as bytes, because ``write_index`` is
    unconditional — it would happily re-render a byte-identical file and only
    the timestamp would show it.
    """
    _seeded(store)
    _freshen_index(store)
    before = {
        name: (p.read_bytes(), p.stat().st_mtime_ns)
        for name in INDEX_FILES
        for p in [store.project_dir / name]
    }

    assert ensure_fresh(store) is False

    after = {
        name: (p.read_bytes(), p.stat().st_mtime_ns)
        for name in INDEX_FILES
        for p in [store.project_dir / name]
    }
    assert after == before


def test_ensure_fresh_leaves_the_index_ahead_of_every_item(store):
    """After a rebuild the same reader must not rebuild again."""
    _seeded(store)
    _age_index(store)

    assert ensure_fresh(store) is True
    assert ensure_fresh(store) is False


def test_ensure_fresh_rebuilds_the_markdown_indexes_too(store):
    """The four markdown renders are derived from the same data."""
    _story_id, task_id = _seeded(store)
    store.update(task_id, status="done")
    _age_index(store)

    ensure_fresh(store)

    assert "done" in (store.project_dir / "INDEX-TASKS.md").read_text()


def test_ensure_fresh_is_a_no_op_without_a_project_dir(tmp_path, store):
    """A reader pointed at a directory that is not there must not explode."""
    store.project_dir = tmp_path / "not-a-project"
    store.stories_dir = store.project_dir / "stories"
    store.tasks_dir = store.project_dir / "tasks"
    store.epics_dir = store.project_dir / "epics"

    assert ensure_fresh(store) is False
    assert not store.project_dir.exists()
