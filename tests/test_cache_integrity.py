"""Cache integrity: what a cached read hands out must not be the cache's own list.

The blanket ``deepcopy`` on every cached read was removed in 0.8.4 (US-PRJ-37).
That makes the *models* in a returned list shared with the cache — deliberately,
that is the speedup — but the **list object** must still be the caller's own, so
a caller doing ``.append()`` or ``.sort()`` cannot corrupt what the next
``list_*`` call returns.

The first half of this module (US-PRJ-37-5) is narrow: list identity only.  The
broad suite below it (US-PRJ-37-6) pins the rest of the contract — repeated
reads, write-path invalidation, external-edit detection, and the exact blast
radius of the one hazard the no-copy design accepts.

**Option A was chosen** for US-PRJ-37-6: cached reads keep handing back the
cache's own model instances, and "callers treat returned models as read-only"
stays the contract.  Option B (a per-item ``model_copy`` on every read) was
measured on a 1000-task store and rejected — see ``docs/reference/cache-semantics.md``
for the numbers.  These tests therefore assert *cache/disk agreement* after
every write, not model isolation.
"""

import os
import shutil
import time

import frontmatter
import pytest
import yaml

from projectman.store import Store, _cache, clear_all_caches


@pytest.fixture
def populated(store):
    """A store with three stories, each carrying a task, plus two epics."""
    for n in (1, 2, 3):
        story, _ = store.create_story(f"Story {n}", f"Body {n}")
        store.create_task(story.id, f"Task {n}", f"Task body {n}")
    for n in (1, 2):
        store.create_epic(f"Epic {n}", f"Epic body {n}")
    return store


def _ids(items):
    return [m.id for m in items]


@pytest.mark.parametrize(
    "method",
    ["list_tasks", "list_stories", "list_epics"],
)
def test_mutating_returned_list_does_not_affect_cache(populated, method):
    """append/sort/clear on a returned list must not change the next call's result."""
    first = getattr(populated, method)()
    baseline = _ids(first)
    assert len(baseline) >= 2, "fixture must yield enough items to reorder"

    # Three different in-place mutations, each on a freshly returned list.
    first.append(first[0])
    first.sort(key=lambda m: m.id, reverse=True)

    second = getattr(populated, method)()
    assert _ids(second) == baseline

    second.clear()
    assert _ids(getattr(populated, method)()) == baseline


def test_returned_list_is_not_the_cache_list(populated):
    """The identity check behind the test above, stated directly."""
    for item_type, method in (
        ("tasks", "list_tasks"),
        ("stories", "list_stories"),
        ("epics", "list_epics"),
    ):
        key = populated._cache_key(item_type)
        # The cache is lazily populated: create_* only appends to an already
        # warm cache, so prime it with a read first.
        returned = getattr(populated, method)()
        assert key in _cache, f"{item_type} cache should be populated"
        assert returned is not _cache[key]
        assert getattr(populated, method)() is not _cache[key]


def test_list_tasks_with_bodies_returns_a_fresh_list(populated):
    """The unfiltered path is the risky one: it starts as ``result = _cache[key]``."""
    key = populated._cache_key("tasks")
    unfiltered = populated.list_tasks_with_bodies()
    assert key in _cache
    assert unfiltered is not _cache[key]

    baseline = [m.id for m, _ in unfiltered]
    unfiltered.append(unfiltered[0])
    unfiltered.sort(key=lambda pair: pair[0].id, reverse=True)

    assert [m.id for m, _ in populated.list_tasks_with_bodies()] == baseline
    assert [m.id for m in populated.list_tasks()] == baseline


def test_list_all_does_not_leak_cached_objects(populated):
    """``list_all`` builds dicts; mutating them must not reach the cached models."""
    dumped = populated.list_all("stories")
    assert dumped, "expected stories"
    dumped[0]["title"] = "clobbered"
    dumped.clear()

    again = populated.list_all("stories")
    assert "clobbered" not in [d["title"] for d in again]
    assert [s.title for s in populated.list_stories()] == [
        d["title"] for d in again
    ]


def test_mutating_a_returned_model_leaks_into_the_cache(populated):
    """KNOWN LIMITATION, pinned deliberately: models are shared, not copied.

    Dropping the blanket ``deepcopy`` (US-PRJ-37) means a model handed back by
    ``list_tasks``/``get_task`` **is** the cache's own instance.  Mutating it —
    including its nested mutable fields, which are the easy trap — is therefore
    visible to the next reader in the process, and disagrees with the file on
    disk.  That is why ``docs/reference/cache-semantics.md`` states the
    read-only rule: this test asserts the hazard the rule exists to prevent,
    not a guarantee callers may rely on.
    """
    meta = populated.list_tasks()[0]
    original_status = meta.status
    original_tags = list(meta.tags)

    # get_task hands back the very same object, not a copy.
    assert populated.get_task(meta.id)[0] is meta

    meta.tags.append("leaked-via-inner-list")
    meta.status = "blocked"

    # The leak: the next read sees the caller's edit.
    refetched, _ = populated.get_task(meta.id)
    assert refetched.tags == original_tags + ["leaked-via-inner-list"]
    assert refetched.status == "blocked"

    # ...and disk never saw it, so the cache now disagrees with the file.
    on_disk = {m.id: m for m, _ in populated._read_tasks_from_disk()}[meta.id]
    assert on_disk.tags == original_tags
    assert on_disk.status == original_status

    # Leave the cache clean for whatever runs next in this process.
    meta.tags[:] = original_tags
    meta.status = original_status


# ───────────────────────────────────────────────────────────────────────
# US-PRJ-37-6 — the broad integrity suite
#
# Everything below runs against a realistic corpus (3 epics / 10 stories /
# 50 tasks) built through the Store API in a tmp directory.  The real
# ``.project`` is never touched.
# ───────────────────────────────────────────────────────────────────────

KINDS = ("epics", "stories", "tasks")


@pytest.fixture(scope="module")
def _corpus_template(tmp_path_factory):
    """Build the shared corpus **once**: 3 epics, 10 stories, 50 tasks.

    Module-scoped because writing 63 items through the Store API is the slow
    part of this file.  No test uses it directly — each gets a private copy
    (see :func:`corpus`), so a write test can never leak into a read test.
    """
    root = tmp_path_factory.mktemp("cache_integrity_corpus")
    proj = root / ".project"
    (proj / "stories").mkdir(parents=True)
    (proj / "tasks").mkdir()
    (proj / "config.yaml").write_text(
        yaml.dump(
            {
                "name": "cache-integrity",
                "prefix": "CIT",
                "description": "cache integrity corpus",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            }
        )
    )
    clear_all_caches()
    store = Store(root)
    epics = [store.create_epic(f"Epic {n}", f"Epic body {n}") for n in (1, 2, 3)]
    for n in range(1, 11):
        story, _ = store.create_story(f"Story {n}", f"Story body {n}")
        store.update(story.id, epic_id=epics[(n - 1) % 3].id)
        for t in range(1, 6):
            store.create_task(story.id, f"Task {n}.{t}", f"Task body {n}.{t}")
    clear_all_caches()
    return root


@pytest.fixture
def corpus(_corpus_template, tmp_path):
    """A private copy of the corpus, with the module cache cleared either side."""
    root = tmp_path / "proj"
    shutil.copytree(_corpus_template, root)
    clear_all_caches()
    yield Store(root)
    clear_all_caches()


def _snapshot(store) -> dict[str, dict[str, dict]]:
    """Everything the store will hand out, keyed by id — frontmatter *and* body.

    ``list_all`` is the widest read there is (it dumps the cached models), so
    comparing two snapshots compares every field of every cached item.
    """
    return {
        kind: {item["id"]: item for item in store.list_all(kind)} for kind in KINDS
    }


def _snapshot_from_disk(store) -> dict[str, dict[str, dict]]:
    """The same snapshot, forced to come from the files: ground truth."""
    clear_all_caches()
    return _snapshot(store)


def _item_id(item):
    """id of a model, a ``(meta, body)`` pair, or a ``list_all`` dict."""
    if isinstance(item, dict):
        return item["id"]
    if isinstance(item, tuple):
        return item[0].id
    return item.id


def test_corpus_is_the_size_the_suite_assumes(corpus):
    """Guards every count-sensitive assertion below."""
    snap = _snapshot(corpus)
    assert len(snap["epics"]) == 3, "corpus must hold 3 epics"
    assert len(snap["stories"]) == 10, "corpus must hold 10 stories"
    assert len(snap["tasks"]) == 50, "corpus must hold 50 tasks"


# --- 1. repeated reads are consistent ----------------------------------


def test_repeated_reads_return_equal_data(corpus):
    """Invariant: a read with no intervening write is idempotent, forever."""
    first = _snapshot(corpus)
    for n in range(1, 6):
        assert _snapshot(corpus) == first, (
            f"read #{n} diverged from the first with no write in between — "
            "a cached read must be idempotent"
        )


def test_repeated_reads_return_the_same_instances(corpus):
    """Option A, stated as a test: reads share the cache's objects, no copy.

    This is the *reason* the read-only rule exists.  If this ever starts
    failing, someone reintroduced a per-read copy and the rule (and the
    performance argument behind US-PRJ-37) needs revisiting — see
    ``docs/reference/cache-semantics.md``.
    """
    tasks, stories, epics = corpus.list_tasks(), corpus.list_stories(), corpus.list_epics()
    for n in range(1, 4):
        assert all(a is b for a, b in zip(corpus.list_tasks(), tasks)), (
            f"list_tasks call #{n} handed back different objects — "
            "option A promises zero-copy reads"
        )
        assert all(a is b for a, b in zip(corpus.list_stories(), stories)), (
            f"list_stories call #{n} handed back different objects"
        )
        assert all(a is b for a, b in zip(corpus.list_epics(), epics)), (
            f"list_epics call #{n} handed back different objects"
        )
        assert corpus.get_task(tasks[0].id)[0] is tasks[0], (
            "get_task must serve the same instance list_tasks did"
        )
        assert corpus.get_story(stories[0].id)[0] is stories[0], (
            "get_story must serve the same instance list_stories did"
        )
        assert corpus.get_epic(epics[0].id)[0] is epics[0], (
            "get_epic must serve the same instance list_epics did"
        )
        assert corpus.get(tasks[0].id)[0] is tasks[0], (
            "get() dispatch must not introduce a copy get_task does not make"
        )


# --- 2. every list return is the caller's own list ---------------------

_LIST_CALLS = {
    "list_tasks": lambda s: s.list_tasks(),
    "list_tasks_by_status": lambda s: s.list_tasks(status="todo"),
    "list_tasks_by_story": lambda s: s.list_tasks(story_id=s.list_stories()[0].id),
    "list_tasks_active_only": lambda s: s.list_tasks(archived=False),
    "list_tasks_with_bodies": lambda s: s.list_tasks_with_bodies(),
    "list_tasks_with_bodies_filtered": lambda s: s.list_tasks_with_bodies(status="todo"),
    "list_stories": lambda s: s.list_stories(),
    "list_stories_by_status": lambda s: s.list_stories(status="backlog"),
    "list_epics": lambda s: s.list_epics(),
    "list_epics_by_status": lambda s: s.list_epics(status="draft"),
    "list_all_epics": lambda s: s.list_all("epics"),
    "list_all_stories": lambda s: s.list_all("stories"),
    "list_all_tasks": lambda s: s.list_all("tasks"),
}


@pytest.mark.parametrize("call_name", sorted(_LIST_CALLS))
def test_every_list_return_is_independent_of_the_cache(corpus, call_name):
    """Invariant: append/sort/clear on a returned list cannot reach the cache.

    Covers the filtered paths too — those build a new list anyway, but the
    unfiltered ones are the paths that start life as ``result = _cache[key]``.
    """
    call = _LIST_CALLS[call_name]
    returned = call(corpus)
    baseline = [_item_id(i) for i in returned]
    assert len(baseline) >= 2, f"{call_name} must return enough items to reorder"

    for kind in KINDS:
        assert returned is not _cache.get(corpus._cache_key(kind)), (
            f"{call_name} returned the cache's own list object"
        )

    returned.append(returned[0])
    returned.sort(key=_item_id, reverse=True)
    assert [_item_id(i) for i in call(corpus)] == baseline, (
        f"mutating {call_name}'s result changed the next {call_name} call"
    )

    returned.clear()
    assert [_item_id(i) for i in call(corpus)] == baseline, (
        f"clearing {call_name}'s result emptied the cache"
    )


# --- 3. every write path leaves the cache agreeing with disk -----------

_WRITE_OPS = {
    "update_task_status": lambda s: s.update(s.list_tasks()[0].id, status="in-progress"),
    "update_task_fields": lambda s: s.update(
        s.list_tasks()[1].id, points=3, assignee="worker", tags=["alpha", "beta"]
    ),
    "update_task_body": lambda s: s.update(s.list_tasks()[2].id, body="rewritten body"),
    "update_task_clear": lambda s: (
        s.update(s.list_tasks()[3].id, assignee="worker"),
        s.update(s.list_tasks()[3].id, clear="assignee"),
    ),
    "update_story_status": lambda s: s.update(s.list_stories()[0].id, status="active"),
    "update_story_fields": lambda s: s.update(
        s.list_stories()[1].id, points=5, priority="must", tags=["gamma"]
    ),
    "update_epic_status": lambda s: s.update(s.list_epics()[0].id, status="active"),
    "update_epic_fields": lambda s: s.update(s.list_epics()[1].id, points=8),
    "create_task": lambda s: s.create_task(s.list_stories()[0].id, "Fresh task", "fresh"),
    "create_story": lambda s: s.create_story("Fresh story", "fresh"),
    "create_epic": lambda s: s.create_epic("Fresh epic", "fresh"),
    "claim_task": lambda s: s.claim_task(s.list_tasks()[4].id, "claude"),
    "archive_task": lambda s: s.archive(s.list_tasks()[5].id),
    "archive_story": lambda s: s.archive(s.list_stories()[2].id),
    "archive_epic": lambda s: s.archive(s.list_epics()[2].id),
    "bulk_update_ten_tasks": lambda s: [
        s.update(t.id, status="review") for t in s.list_tasks()[:10]
    ],
    "bulk_archive_ten_tasks": lambda s: [s.archive(t.id) for t in s.list_tasks()[10:20]],
    "bulk_archive_three_stories": lambda s: [
        s.archive(st.id) for st in s.list_stories()[:3]
    ],
    # A round trip: the end state matches the start state, so it is exempt
    # from the "something changed" assertion — but the cache must still agree
    # with disk afterwards, which is the point.
    "archive_then_unarchive_task": lambda s: (
        s.archive(s.list_tasks()[6].id),
        s.unarchive(s.list_tasks()[6].id),
    ),
}

_NEUTRAL_OPS = {"archive_then_unarchive_task", "update_task_clear"}


@pytest.mark.parametrize("op_name", sorted(_WRITE_OPS))
def test_write_paths_leave_the_cache_consistent_with_disk(corpus, op_name):
    """Invariant: after any write, a cached read == a cache-cleared disk read.

    This is the whole safety argument for keeping the cache warm across
    writes.  ``Store.update`` refreshes one entry surgically while the
    directory mtime/count check may also invalidate wholesale; either route
    is fine, but the observable result must be the files' contents.
    """
    before = _snapshot(corpus)  # also warms all three caches
    _WRITE_OPS[op_name](corpus)

    after_cached = _snapshot(corpus)
    if op_name not in _NEUTRAL_OPS:
        assert after_cached != before, (
            f"{op_name} wrote to disk but the next cached read saw nothing — "
            "the cache is serving stale data"
        )

    after_disk = _snapshot_from_disk(corpus)
    for kind in KINDS:
        assert after_cached[kind] == after_disk[kind], (
            f"after {op_name} the cached {kind} disagree with the files on "
            "disk — a write path failed to invalidate or refresh the cache"
        )


def test_a_write_is_visible_to_get_and_list_alike(corpus):
    """Invariant: invalidation is not per-method — every reader sees the write."""
    task = corpus.list_tasks()[0]
    corpus.get_task(task.id)  # warm the scalar path too
    corpus.update(task.id, status="blocked", assignee="someone")

    assert corpus.get_task(task.id)[0].status.value == "blocked", "get_task stale"
    assert corpus.get(task.id)[0].status.value == "blocked", "get() dispatch stale"
    assert [m.status.value for m in corpus.list_tasks() if m.id == task.id] == [
        "blocked"
    ], "list_tasks stale"
    assert [
        m.status.value for m, _ in corpus.list_tasks_with_bodies() if m.id == task.id
    ] == ["blocked"], "list_tasks_with_bodies stale"
    assert [d["status"] for d in corpus.list_all("tasks") if d["id"] == task.id] == [
        "blocked"
    ], "list_all stale"
    assert corpus.list_tasks(status="blocked") != [], "status filter stale"


# --- 4. external edits are detected ------------------------------------


@pytest.mark.parametrize("kind", ["tasks", "stories", "epics"])
def test_an_external_file_edit_invalidates_the_cache(corpus, kind):
    """Invariant: a write this process did not make is still picked up.

    ``_is_cache_stale`` compares the directory's newest mtime and file count
    against what was stored when the cache was filled.  ``os.utime`` pins the
    mtime bump so the test does not depend on filesystem timestamp
    granularity.
    """
    reader = {
        "tasks": corpus.list_tasks,
        "stories": corpus.list_stories,
        "epics": corpus.list_epics,
    }[kind]
    getter = {
        "tasks": corpus.get_task,
        "stories": corpus.get_story,
        "epics": corpus.get_epic,
    }[kind]
    path_of = {
        "tasks": corpus._task_path,
        "stories": corpus._story_path,
        "epics": corpus._epic_path,
    }[kind]

    victim = reader()[0]
    assert getter(victim.id)[0].title == victim.title, "cache must be warm first"

    path = path_of(victim.id)
    post = frontmatter.load(str(path))
    post.metadata["title"] = "Edited outside this process"
    post.content = "Body rewritten on disk"
    path.write_text(frontmatter.dumps(post))
    future = time.time() + 5
    os.utime(path, (future, future))

    meta, body = getter(victim.id)
    assert meta.title == "Edited outside this process", (
        f"get_{kind[:-1]} served a cached copy of a file edited on disk"
    )
    assert body == "Body rewritten on disk", "the cached body was served too"
    assert [m.title for m in reader() if m.id == victim.id] == [
        "Edited outside this process"
    ], f"list_{kind} served a cached copy of a file edited on disk"


def test_an_external_file_deletion_invalidates_the_cache(corpus):
    """The file-count half of the staleness check, which mtime alone misses."""
    tasks = corpus.list_tasks()
    victim = tasks[0]
    corpus._task_path(victim.id).unlink()

    remaining = corpus.list_tasks()
    assert len(remaining) == len(tasks) - 1, (
        "a task file removed on disk is still being served from the cache"
    )
    assert victim.id not in [m.id for m in remaining]


# --- 5. the accepted hazard, and how far it reaches ---------------------


def test_a_leaked_model_edit_never_reaches_disk(corpus):
    """The bound on the hazard: it is process-local, ground truth is safe."""
    meta = corpus.list_tasks()[0]
    original = meta.status
    meta.status = "blocked"

    on_disk = {m.id: m for m, _ in corpus._read_tasks_from_disk()}[meta.id]
    assert on_disk.status == original, (
        "mutating a returned model wrote through to the file — the no-copy "
        "design must never make a caller's edit durable"
    )


def test_a_leaked_model_edit_is_healed_by_clearing_the_cache(corpus):
    """The recovery path: ``clear_all_caches`` restores the files' truth."""
    meta = corpus.list_tasks()[0]
    original_status, original_tags = meta.status, list(meta.tags)
    meta.status = "blocked"
    meta.tags.append("leaked")

    clear_all_caches()
    healed, _ = corpus.get_task(meta.id)
    assert healed.status == original_status, "cache clear did not undo the leak"
    assert healed.tags == original_tags, "cache clear did not undo the inner-list leak"


def test_a_leaked_model_edit_is_healed_by_the_next_write(corpus):
    """``Store.update`` re-reads the file, so it cannot preserve a leak.

    Matters because it bounds the hazard in practice: any write to the item
    replaces the poisoned cache entry with one built from disk, so a stray
    caller edit cannot survive the item's next legitimate update.
    """
    meta = corpus.list_tasks()[0]
    original_tags = list(meta.tags)
    meta.tags.append("leaked")
    meta.assignee = "ghost"

    corpus.update(meta.id, points=2)

    refetched, _ = corpus.get_task(meta.id)
    assert refetched.tags == original_tags, (
        "an update rebuilt the cache entry from a leaked model, not from disk"
    )
    assert refetched.assignee != "ghost", (
        "an update preserved a caller's in-memory edit instead of the file's value"
    )
    assert refetched.points == 2, "the update itself did not land"
    assert _snapshot(corpus) == _snapshot_from_disk(corpus), (
        "cache and disk disagree after a write over a leaked entry"
    )


# ---------------------------------------------------------------------------
# US-PRJ-39: the cached entries carry an ID index, so update / evict-on-archive
# / by-ID reads are O(1).  The full consistency suite is US-PRJ-39-5; what is
# pinned here is that the new structure is in place and stays in step with the
# entries it indexes.
# ---------------------------------------------------------------------------


def test_cache_value_is_the_id_indexed_container(populated):
    """A warm cache holds ``_CacheEntries``, whose index matches its entries."""
    from projectman.store import _CacheEntries

    populated.list_tasks()
    key = populated._cache_key("tasks")
    entries = _cache[key]
    assert isinstance(entries, _CacheEntries)
    assert entries.ids() == [m.id for m, _ in entries]
    for meta, body in entries:
        assert entries.lookup(meta.id) == (meta, body)
    assert entries.lookup("US-NOPE-9-9") is None


def test_update_replaces_the_indexed_entry_in_place(populated):
    """``_cache_update_entry`` finds the ID through the index, order intact."""
    populated.list_tasks()
    key = populated._cache_key("tasks")
    before = _cache[key].ids()
    target = before[0]

    populated.update(target, points=3)

    entries = _cache[key]
    assert entries.ids() == before, "an update reordered or dropped cache entries"
    assert entries.ids() == [m.id for m, _ in entries], "index out of step"
    meta, _ = entries.lookup(target)
    assert meta.points == 3


def test_archiving_a_story_evicts_it_from_the_index(populated):
    """Evict-on-archive drops the ID from both the entries and the index."""
    populated.list_stories()
    key = populated._cache_key("stories")
    target = _cache[key].ids()[0]

    populated.archive(target)

    entries = _cache[key]
    assert target not in entries.ids()
    assert entries.lookup(target) is None
    assert entries.ids() == [m.id for m, _ in entries], "index out of step"
    assert target not in [m.id for m in populated.list_stories()]


def test_append_indexes_the_new_item(populated):
    """A create against a warm cache indexes the appended entry."""
    populated.list_stories()
    key = populated._cache_key("stories")
    story, _ = populated.create_story("Indexed", "Body")

    entries = _cache[key]
    assert entries.ids()[-1] == story.id
    assert entries.lookup(story.id)[0].title == "Indexed"


def test_invalidation_drops_the_index_with_the_entries(populated):
    """Whole-key invalidation cannot leave a stale index behind."""
    populated.list_tasks()
    key = populated._cache_key("tasks")
    populated._invalidate_cache("tasks")
    assert key not in _cache


# ---------------------------------------------------------------------------
# US-PRJ-39-5 — the consistency proof.
#
# Two things have to hold for the ID index to be worth having:
#
# 1. it never drifts from the entries it indexes — same IDs, same order, after
#    every create / update / archive / invalidate; and
# 2. the by-ID paths actually *use* it.  A dict beside a list that everyone
#    still scans is a slower list, so the second half of this section counts
#    every walk of the container while a lookup, an update and an
#    evict-on-archive run, and requires the count to stay at zero — including
#    against a 500-item cache, where an O(n) scan would be the whole cost.
# ---------------------------------------------------------------------------


def _assert_index_agrees(entries, *, expected_ids=None):
    """The index and the entries must name the same items in the same order."""
    from projectman.store import _CacheEntries

    assert isinstance(entries, _CacheEntries)
    walked = list(entries)  # goes through __iter__, i.e. the entries themselves
    walked_ids = [meta.id for meta, _ in walked]
    assert entries.ids() == walked_ids, "index and entries disagree on ids or order"
    assert len(entries) == len(walked_ids), "len() disagrees with the entries"
    assert len(set(walked_ids)) == len(walked_ids), "an id is cached twice"
    for meta, body in walked:
        found = entries.lookup(meta.id)
        assert found is not None, f"{meta.id} is in the entries but not the index"
        assert found[0] is meta and found[1] == body, (
            f"the index points {meta.id} at a different entry"
        )
    if expected_ids is not None:
        assert walked_ids == list(expected_ids)
    return walked_ids


def test_index_agrees_with_entries_across_the_whole_lifecycle(populated):
    """create → update → archive → invalidate: the index never drifts."""
    populated.list_stories()  # warm the cache; create_* only appends to a warm one
    key = populated._cache_key("stories")
    baseline = _assert_index_agrees(_cache[key])

    # --- create: appended at the end, indexed, nothing else moved ---------
    created, _ = populated.create_story("Lifecycle", "Body")
    after_create = _assert_index_agrees(_cache[key], expected_ids=[*baseline, created.id])

    # --- update: replaced in place, order untouched -----------------------
    populated.update(created.id, points=5)
    _assert_index_agrees(_cache[key], expected_ids=after_create)
    assert _cache[key].lookup(created.id)[0].points == 5

    # --- update of a *middle* entry: still no reordering -------------------
    middle = after_create[len(after_create) // 2]
    populated.update(middle, title="Renamed in the middle")
    _assert_index_agrees(_cache[key], expected_ids=after_create)
    assert _cache[key].lookup(middle)[0].title == "Renamed in the middle"

    # --- archive: evicted from both halves, the rest keeps its order ------
    populated.archive(middle)
    survivors = [i for i in after_create if i != middle]
    _assert_index_agrees(_cache[key], expected_ids=survivors)
    assert _cache[key].lookup(middle) is None

    # --- invalidate: the index cannot outlive the entries ------------------
    populated._invalidate_cache("stories")
    assert key not in _cache, "invalidation left something behind under the key"

    # --- and the rebuild from disk agrees with what the cache had ---------
    live = populated.list_stories()
    rebuilt = _assert_index_agrees(_cache[key])
    assert sorted(rebuilt) == sorted(survivors), (
        "the cache rebuilt from disk holds a different set than it did in memory"
    )
    assert rebuilt == [meta.id for meta in live], (
        "list_stories and the cached entries disagree after a rebuild"
    )


@pytest.mark.parametrize("kind", ["epics", "stories", "tasks"])
def test_index_agrees_for_every_cached_kind(populated, kind):
    """The same create/update/invalidate agreement, per cached item type."""
    warm = {"epics": populated.list_epics, "stories": populated.list_stories,
            "tasks": populated.list_tasks}[kind]
    warm()
    key = populated._cache_key(kind)
    baseline = _assert_index_agrees(_cache[key])
    assert baseline, f"{kind} fixture cached nothing to check"

    if kind == "epics":
        new_id = populated.create_epic("Fresh", "Body").id
    elif kind == "stories":
        new_id = populated.create_story("Fresh", "Body")[0].id
    else:
        new_id = populated.create_task(
            populated.list_stories()[0].id, "Fresh", "Body"
        ).id
    expected = [*baseline, new_id]
    _assert_index_agrees(_cache[key], expected_ids=expected)

    populated.update(new_id, title="Fresh, renamed")
    _assert_index_agrees(_cache[key], expected_ids=expected)
    assert _cache[key].lookup(new_id)[0].title == "Fresh, renamed"

    populated._invalidate_cache(kind)
    assert key not in _cache
    warm()
    assert sorted(_assert_index_agrees(_cache[key])) == sorted(expected)


@pytest.fixture
def scan_counter(monkeypatch):
    """Count every walk of a ``_CacheEntries`` — the O(n) path we must not take.

    The probe delegates to the real iterator rather than raising, so a scan is
    reported as a count in the failure message instead of surfacing as some
    unrelated error further down a call stack that swallows exceptions.
    """
    from projectman.store import _CacheEntries

    real_iter = _CacheEntries.__iter__
    scans: list[int] = []

    def counting_iter(self):
        scans.append(len(self))
        return real_iter(self)

    monkeypatch.setattr(_CacheEntries, "__iter__", counting_iter)
    return scans


def test_by_id_paths_never_scan_a_500_item_cache(store, scan_counter):
    """Lookup, update and evict-on-archive are all O(1) on a 500-story cache."""
    for n in range(500):
        store.create_story(f"Bulk {n}", f"Body {n}")

    # Warm from disk (the one legitimate scan) *before* the probe matters, then
    # take the counter back to zero: only the by-ID paths below are under test.
    ids = [meta.id for meta in store.list_stories()]
    assert len(ids) == 500, "the 500 creates did not all land"
    key = store._cache_key("stories")
    target = ids[len(ids) // 2]
    assert scan_counter, (
        "the scan probe never fired, so a zero count below would prove nothing"
    )
    scan_counter.clear()

    # --- read by ID --------------------------------------------------------
    meta, body = store.get_story(target)
    # IDs are handed out in creation order, so ``US-TST-<n>`` is the n-1'th
    # create.  (The cached order is the filename sort the disk read produced,
    # which is not creation order — hence deriving this from the ID.)
    nth = int(target.rsplit("-", 1)[1]) - 1
    assert meta.id == target and body == f"Body {nth}"
    assert scan_counter == [], (
        f"get_story walked the cached entries {len(scan_counter)}x instead of "
        "using the index"
    )

    # --- update by ID ------------------------------------------------------
    store.update(target, points=3)
    assert scan_counter == [], (
        f"the update walked the cached entries {len(scan_counter)}x"
    )
    assert _cache[key].lookup(target)[0].points == 3
    assert _cache[key].ids() == ids, "the update reordered a 500-item cache"

    # --- evict on archive --------------------------------------------------
    store.archive(target)
    assert scan_counter == [], (
        f"evict-on-archive walked the cached entries {len(scan_counter)}x"
    )
    assert _cache[key].lookup(target) is None
    assert _cache[key].ids() == [i for i in ids if i != target], (
        "eviction disturbed the surviving entries"
    )


def test_task_and_epic_by_id_reads_never_scan(populated, scan_counter):
    """The same no-scan guarantee on the other two caches."""
    task_id = populated.list_tasks()[0].id
    epic_id = populated.list_epics()[0].id
    assert scan_counter, "the scan probe never fired; the assertions below are empty"
    scan_counter.clear()

    assert populated.get_task(task_id)[0].id == task_id
    assert populated.get_epic(epic_id)[0].id == epic_id
    assert scan_counter == [], "a by-ID read scanned the cache"

    populated.update(task_id, points=2)
    populated.update(epic_id, title="Renamed epic")
    assert scan_counter == [], "an update scanned the cache"
    assert _cache[populated._cache_key("tasks")].lookup(task_id)[0].points == 2
    assert (
        _cache[populated._cache_key("epics")].lookup(epic_id)[0].title
        == "Renamed epic"
    )
