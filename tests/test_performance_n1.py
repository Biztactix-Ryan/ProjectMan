"""N+1 regression scaffolding: a 100-task project and a Store call spy.

The performance work on ``pm_board``, ``pm_epic`` and ``pm_search`` replaced
per-item ``Store`` reads with batch loads.  Nothing stops a later refactor
from quietly reintroducing the per-item call — the output would still be
correct, just O(n) reads instead of one.  This module supplies the two pieces
a regression test for that needs:

* :func:`n1_project` — a project big enough that an N+1 pattern is
  unmistakable in the counts (10 stories, 100 tasks, 3 epics), and
* the ``store_spy`` fixture from ``tests/conftest.py``, which counts every
  ``Store`` read the process makes.

The tool-level assertions built on top of these live in US-PRJ-63-6; what is
here is the fixtures plus a smoke test proving the spy counts and records
accurately.
"""

import pytest
import yaml


#: A task body that clears every readiness check: past the thin-description
#: threshold, with the Implementation / Testing / Definition of Done sections
#: ``readiness`` looks for.  ``{n}`` is substituted so no two tasks share a
#: body — a batch loader that handed every task the same body would then be
#: visible in the output, not just in the call counts.
READY_TASK_BODY = """\
## Implementation

Wire handler number {n} into the API router, validating the request payload
before it reaches the service layer and mapping errors onto status codes.

## Testing

Run pytest tests/test_handler_{n}.py to verify the endpoint behaves.

## Definition of Done

- [ ] Handler {n} responds
- [ ] Errors mapped to status codes
"""

#: Fixture shape, asserted by :func:`test_n1_project_has_the_documented_shape`
#: so the numbers other tests reason about cannot drift silently.
N1_EPICS = 3
N1_STORIES = 10
N1_TASKS_PER_STORY = 10
N1_TASKS = N1_STORIES * N1_TASKS_PER_STORY
#: Stories whose tasks form a linear depends_on chain (task n waits on n-1).
N1_CHAINED_STORIES = (1, 2, 3)
#: Tasks archived after creation — they stay on disk and in listings.
N1_ARCHIVED_TASK_IDS = ("US-TST-10-8", "US-TST-10-9", "US-TST-10-10")
#: Tasks carrying the "api" tag, for the pm_search tag-filter tests.
N1_TAGGED_TASK_IDS = ("US-TST-4-1", "US-TST-5-1")


@pytest.fixture(scope="session")
def _n1_template(tmp_path_factory):
    """Scratch root holding one built copy of the fixture project.

    Building 3 epics, 10 stories and 100 tasks through the server tools costs
    roughly 1.5s, and every test in this module wants a project of its own to
    write to.  So the build happens once per session into this directory and
    :func:`n1_project` copies the resulting ``.project`` tree per test —
    copying ~115 small files is two orders of magnitude cheaper than
    rebuilding one, and each test still gets a private tree.
    """
    return tmp_path_factory.mktemp("n1-template")


@pytest.fixture
def n1_project(tmp_project, _n1_template, monkeypatch):
    """A 100-task project, built through the server tools, cache warmed.

    Function-scoped on purpose: ``tmp_project`` is function-scoped, the
    server's ``_store_cache`` and the store's module-level ``_cache`` are
    process-global, and the tools mutate on write — a shared module-scoped
    *project* would leak state between tests.  What is shared is the build
    output on disk (see :func:`_n1_template`), copied fresh into each test's
    own root.

    Layout:

    * ``EPIC-TST-1..3``; stories 1-4 hang off the first, 5-8 off the second,
      9-10 off the third, so ``pm_epic`` has a multi-story epic to partition.
    * ``US-TST-1..10``, all ``active``, 10 tasks apiece = 100 tasks, every one
      pointed with a body that passes readiness.
    * Stories 1-3 chain their tasks with ``depends_on`` (task *n* waits on
      *n-1*), so only the first task of each is available and the dependency
      branch of ``check_readiness`` runs 27 times.
    * ``US-TST-10-8/9/10`` are archived.
    * ``US-TST-4-1`` and ``US-TST-5-1`` are tagged ``api``, as are their
      stories.

    The working directory is the project root, so ``_store()`` inside the
    server tools resolves here.  Returns a dict of the created IDs.
    """
    import shutil

    from projectman.server import (
        _store,
        _store_cache,
        pm_archive,
        pm_create_epic,
        pm_create_story,
        pm_create_tasks,
        pm_update,
    )
    from projectman.store import _cache

    monkeypatch.chdir(tmp_project)
    _store_cache.clear()
    _cache.clear()

    # IDs are deterministic, so they can be named before anything is built —
    # which lets the cached copy skip the build entirely.  The build below
    # asserts the tools really do produce these, so the two paths cannot
    # describe different projects.
    epic_ids = [f"EPIC-TST-{n}" for n in range(1, N1_EPICS + 1)]
    story_ids = [f"US-TST-{n}" for n in range(1, N1_STORIES + 1)]
    task_ids = [
        f"US-TST-{n}-{t}"
        for n in range(1, N1_STORIES + 1)
        for t in range(1, N1_TASKS_PER_STORY + 1)
    ]
    # Stories 1-4 -> epic 1, 5-8 -> epic 2, 9-10 -> epic 3.
    epic_for_story = {n: epic_ids[min((n - 1) // 4, N1_EPICS - 1)] for n in range(1, N1_STORIES + 1)}

    template = _n1_template / ".project"
    if template.exists():
        shutil.rmtree(tmp_project / ".project")
        shutil.copytree(template, tmp_project / ".project")
    else:
        built_epics = [
            yaml.safe_load(pm_create_epic(f"Epic {n}", "Epic description " * 5))[
                "created"
            ]["id"]
            for n in range(1, N1_EPICS + 1)
        ]
        assert built_epics == epic_ids

        built_stories = []
        built_tasks = []
        for n in range(1, N1_STORIES + 1):
            created = yaml.safe_load(
                pm_create_story(
                    f"Story {n}",
                    f"As a user, I want feature {n} so that the workflow completes.",
                    epic_id=epic_for_story[n],
                    tags="api" if n in (4, 5) else None,
                )
            )["created"]
            story_id = created["id"]
            built_stories.append(story_id)
            pm_update(story_id, status="active")

            entries = []
            for t in range(1, N1_TASKS_PER_STORY + 1):
                entry = {
                    "title": f"Task {t} of story {n}",
                    "description": READY_TASK_BODY.format(n=f"{n}_{t}"),
                    "points": (1, 2, 3, 5)[t % 4],
                }
                if n in N1_CHAINED_STORIES and t > 1:
                    entry["depends_on"] = [f"{story_id}-{t - 1}"]
                if f"{story_id}-{t}" in N1_TAGGED_TASK_IDS:
                    entry["tags"] = ["api"]
                entries.append(entry)
            batch = yaml.safe_load(pm_create_tasks(story_id, entries))["created"]
            built_tasks.extend(t["id"] for t in batch)

        for task_id in N1_ARCHIVED_TASK_IDS:
            pm_archive(task_id)

        assert built_stories == story_ids
        assert built_tasks == task_ids
        shutil.copytree(tmp_project / ".project", template)

    # The copy (or the build) landed behind the caches' backs, so drop them
    # and warm them again: a measurement that follows counts the calls the
    # tool makes, not the one-off disk read of a cold cache.
    _store_cache.clear()
    _cache.clear()
    store = _store()
    store.list_tasks()
    store.list_stories()
    store.list_epics()

    return {
        "root": tmp_project,
        "epic_ids": epic_ids,
        "story_ids": story_ids,
        "task_ids": task_ids,
        "archived_task_ids": list(N1_ARCHIVED_TASK_IDS),
        "tagged_task_ids": list(N1_TAGGED_TASK_IDS),
        "epic_for_story": epic_for_story,
    }


def test_n1_project_has_the_documented_shape(n1_project):
    """The fixture builds exactly what the module constants promise."""
    from projectman.server import _store

    store = _store()

    assert len(n1_project["epic_ids"]) == N1_EPICS
    assert n1_project["story_ids"] == [f"US-TST-{n}" for n in range(1, N1_STORIES + 1)]
    assert len(n1_project["task_ids"]) == N1_TASKS

    assert len(store.list_stories()) == N1_STORIES
    assert [s.status.value for s in store.list_stories()] == ["active"] * N1_STORIES
    assert len(store.list_tasks()) == N1_TASKS

    archived = store.list_tasks(archived=True)
    assert sorted(t.id for t in archived) == sorted(N1_ARCHIVED_TASK_IDS)
    assert len(store.list_tasks(archived=False)) == N1_TASKS - len(N1_ARCHIVED_TASK_IDS)

    # Every task is pointed and carries a body that clears the thin-description
    # threshold, and no two tasks share a body.
    entries = store.list_tasks_with_bodies()
    assert all(m.points for m, _ in entries)
    assert all(len(b) > 60 for _, b in entries)
    assert len({b for _, b in entries}) == N1_TASKS

    # Chains: the first task of a chained story has no deps, the rest wait on
    # their predecessor.
    for n in N1_CHAINED_STORIES:
        chain = sorted(store.list_tasks(story_id=f"US-TST-{n}"), key=lambda m: m.id)
        by_num = {int(m.id.rsplit("-", 1)[1]): m for m in chain}
        assert by_num[1].depends_on == []
        for t in range(2, N1_TASKS_PER_STORY + 1):
            assert by_num[t].depends_on == [f"US-TST-{n}-{t - 1}"], (n, t)
    # Unchained stories really are unchained.
    assert all(m.depends_on == [] for m in store.list_tasks(story_id="US-TST-9"))

    tagged = {m.id for m in store.list_tasks() if "api" in m.tags}
    assert tagged == set(N1_TAGGED_TASK_IDS)

    # Epics have stories linked, with the biggest holding four.
    by_epic = {}
    for s in store.list_stories():
        by_epic.setdefault(s.epic_id, []).append(s.id)
    assert set(by_epic) == set(n1_project["epic_ids"])
    assert sorted(len(v) for v in by_epic.values()) == [2, 4, 4]


def test_n1_project_builds_quickly(n1_project):
    """A 100-task build must stay cheap enough to use per test.

    The fixture is function-scoped, so its cost is paid by every test in
    US-PRJ-63.  This pins the *re-read* cost rather than the build itself
    (pytest builds the fixture before the test body runs): with the cache
    warm, listing all 100 tasks must be effectively free.
    """
    import time

    from projectman.server import _store

    store = _store()
    start = time.perf_counter()
    for _ in range(20):
        store.list_tasks()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"20 warm list_tasks calls took {elapsed:.3f}s"


def test_store_spy_counts_and_records_a_known_call_sequence(n1_project, store_spy):
    """The spy counts exactly the calls made, and records how they were made.

    ``n1_project`` is listed first so its build (and cache warm-up) happens
    before the wrappers go on; the explicit ``reset()`` makes that ordering
    a belt-and-braces detail rather than a load-bearing one.
    """
    from projectman.server import _store

    store = _store()
    store_spy.reset()
    assert store_spy.counts == dict.fromkeys(store_spy.counts, 0)

    store.get_task("US-TST-1-1")
    store.list_tasks()
    store.list_tasks(story_id="US-TST-2")
    store.list_stories()

    assert store_spy.counts["get_task"] == 1
    assert store_spy.counts["list_tasks"] == 2
    assert store_spy.counts["list_stories"] == 1
    assert store_spy.counts["get_story"] == 0
    assert store_spy.counts["get"] == 0
    # list_tasks delegates to list_tasks_with_bodies, so the inner call is
    # counted too — a test asserting on one must know about the other.
    assert store_spy.counts["list_tasks_with_bodies"] == 2

    # Order and arguments are recorded, so a test can tell an unfiltered
    # listing from a per-story one.
    assert [c.name for c in store_spy.calls] == [
        "get_task",
        "list_tasks",
        "list_tasks_with_bodies",
        "list_tasks",
        "list_tasks_with_bodies",
        "list_stories",
    ]
    assert store_spy.calls_to("get_task")[0].args == ("US-TST-1-1",)
    list_task_calls = store_spy.calls_to("list_tasks")
    assert (list_task_calls[0].args, list_task_calls[0].kwargs) == ((), {})
    assert list_task_calls[1].kwargs == {"story_id": "US-TST-2"}
    assert store_spy.nonzero() == {
        "get_task": 1,
        "list_tasks": 2,
        "list_tasks_with_bodies": 2,
        "list_stories": 1,
    }

    store_spy.reset()
    assert store_spy.counts == dict.fromkeys(store_spy.counts, 0)
    assert store_spy.calls == []
    assert store_spy.nonzero() == {}


def test_store_spy_records_dispatch_through_get(n1_project, store_spy):
    """``Store.get`` is counted alongside the typed read it dispatches to."""
    from projectman.server import _store

    store = _store()
    store_spy.reset()

    store.get("US-TST-1-1")
    store.get("US-TST-1")
    store.get(n1_project["epic_ids"][0])

    assert store_spy.nonzero() == {
        "get": 3,
        "get_task": 1,
        "get_story": 1,
        "get_epic": 1,
    }
    assert [c.name for c in store_spy.calls] == [
        "get",
        "get_task",
        "get",
        "get_story",
        "get",
        "get_epic",
    ]


def test_store_spy_counts_calls_made_inside_server_tools(n1_project, store_spy):
    """Calls from a server tool's own Store instance are counted.

    The wrappers sit on the class, so it does not matter that ``pm_board``
    builds (or reuses) its own ``Store`` via ``_store()`` — the point of the
    spy is that US-PRJ-63-6 can measure a tool it never handed a store to.
    """
    from projectman.server import pm_board

    store_spy.reset()
    data = yaml.safe_load(pm_board())

    assert data["summary"]["available"] > 0
    assert store_spy.nonzero(), "pm_board made no counted Store reads"
    assert store_spy.counts["list_tasks_with_bodies"] >= 1
    # Whatever the tool did, every recorded call names a spied method and
    # carries its arguments.
    assert all(c.name in store_spy.counts for c in store_spy.calls)


def test_store_spy_reverts_after_the_test(store):
    """No wrapper survives the fixture teardown.

    Runs without ``store_spy``: if the previous tests' wrappers had leaked,
    ``Store.list_tasks`` would still be the ``functools.wraps``-ed closure
    defined in conftest rather than the method defined in ``store.py``.
    """
    from projectman.store import Store

    assert Store.list_tasks.__qualname__ == "Store.list_tasks"
    assert Store.list_tasks.__module__ == "projectman.store"
    assert "conftest" not in Store.list_tasks.__code__.co_filename


# ─── Tool-level N+1 regressions (US-PRJ-63-6) ──────────────────────
#
# Each test below pins one of the batch loads introduced by US-PRJ-43.  The
# pattern is the same throughout: build the 100-task project, ``reset()`` the
# spy immediately before the tool call so only the tool's own reads are
# counted, then assert both the call counts *and* that the tool returned real
# output — a tool that answered with nothing would otherwise make every count
# assertion pass.


def _fake_embedding_module(results):
    """A stand-in ``projectman.embeddings`` whose ``search()`` returns *results*.

    The real module imports numpy and loads an embedding model, neither of
    which is available in the unit environment — and the point here is the
    tag-filter branch that runs *after* the search, not the search itself.
    Pass ``[]`` to make ``pm_search`` fall through to the keyword path.
    """
    import types
    from dataclasses import dataclass

    @dataclass
    class _Result:
        id: str
        title: str
        type: str
        score: float

    module = types.ModuleType("projectman.embeddings")

    class _Store:
        def __init__(self, project_dir):
            self.project_dir = project_dir

        def search(self, query, top_k=10):
            return [_Result(**r) for r in results]

    module.EmbeddingStore = _Store
    return module


def test_pm_board_reads_every_task_in_one_batch(n1_project, store_spy):
    """pm_board on 100 tasks: one tasks read, one stories read, no per-item get.

    Guards US-PRJ-43-5 (bodies loaded once via ``list_tasks_with_bodies``
    instead of ``get_task`` per task) and US-PRJ-43-6 (``check_readiness``
    takes the pre-loaded story/task context instead of looking each parent
    story up itself).  Both regressions would leave the board's *output*
    correct, so only the counts can catch them.
    """
    from projectman.server import pm_board

    store_spy.reset()
    data = yaml.safe_load(pm_board())

    counts = store_spy.counts
    assert counts["get_task"] == 0, (
        "pm_board must not call Store.get_task per task (US-PRJ-43-5); got "
        f"{counts['get_task']} calls for {N1_TASKS} tasks"
    )
    assert counts["get_story"] == 0, (
        "pm_board must not call Store.get_story per task — check_readiness "
        f"takes a pre-loaded story map (US-PRJ-43-6); got {counts['get_story']}"
    )
    assert counts["get"] == 0, (
        f"pm_board must make no Store.get calls; got {counts['get']}"
    )
    # The board reads bodies, and Store.list_tasks delegates *to*
    # list_tasks_with_bodies rather than the other way round — so the
    # metadata-only counter stays at zero and the bodies counter is the one
    # that must be exactly one.
    assert counts["list_tasks_with_bodies"] == 1, (
        "pm_board must call Store.list_tasks_with_bodies exactly once "
        f"(US-PRJ-43-5); got {counts['list_tasks_with_bodies']}"
    )
    assert counts["list_tasks"] == 0, (
        "pm_board must not call Store.list_tasks on top of its one "
        f"list_tasks_with_bodies (US-PRJ-43-6); got {counts['list_tasks']}"
    )
    assert counts["list_stories"] == 1, (
        "pm_board must call Store.list_stories exactly once, not per task "
        f"(US-PRJ-43-6); got {counts['list_stories']}"
    )

    # Non-trivial output: every non-archived task is classified, the chained
    # stories supply the not-ready side, and blockers name the dependency.
    summary = data["summary"]
    classified = sum(summary.values())
    assert classified == N1_TASKS - len(N1_ARCHIVED_TASK_IDS) == 97, summary
    assert summary["available"] >= 90 - 27, summary
    assert summary["not_ready"] == len(N1_CHAINED_STORIES) * (
        N1_TASKS_PER_STORY - 1
    ), summary
    not_ready = {t["id"]: t["blockers"] for t in data["board"]["not_ready"]}
    assert not_ready["US-TST-1-2"] == ["incomplete dependencies: US-TST-1-1"]


@pytest.mark.parametrize(
    "filter_kwargs, expected_summary",
    [
        # An assignee filter skips the readiness branch entirely (`todo and
        # not assignee`), so only the shared per-task story lookup and the
        # body map are left to regress — both still have to be batch loads.
        pytest.param({"assignee": "claude"}, {"in_progress": 2}, id="assignee"),
        # A tag filter keeps readiness, but over the two tagged stories'
        # twenty (unchained, hence available) tasks rather than all 97.
        pytest.param(
            {"tag": "api"}, {"available": 2 * N1_TASKS_PER_STORY}, id="tag"
        ),
    ],
)
def test_pm_board_filters_read_in_one_batch_too(
    n1_project, store_spy, filter_kwargs, expected_summary
):
    """The filtered boards batch their reads exactly as the full board does.

    ``assignee`` and ``tag`` narrow *which* tasks get classified, never how
    many Store reads that costs: both branches run off the same one
    ``list_tasks_with_bodies`` and one ``list_stories``.  Without this, a
    per-task ``get_task``/``get_story`` reintroduced on the filtered paths
    would go unmeasured.
    """
    from projectman.server import pm_board, pm_update

    # Two claimed tasks so the assignee board has something to show — an
    # empty board would satisfy every count assertion for free.
    pm_update("US-TST-6-1", status="in-progress", assignee="claude")
    pm_update("US-TST-7-1", status="in-progress", assignee="claude")

    store_spy.reset()
    data = yaml.safe_load(pm_board(**filter_kwargs))

    counts = store_spy.counts
    assert counts["get_task"] == 0, (
        f"pm_board({filter_kwargs}) must not call Store.get_task per task "
        f"(US-PRJ-43-5); got {counts['get_task']} calls for {N1_TASKS} tasks"
    )
    assert counts["get_story"] == 0, (
        f"pm_board({filter_kwargs}) must not call Store.get_story per task — "
        f"the story map is pre-loaded (US-PRJ-43-6); got {counts['get_story']}"
    )
    assert counts["get"] == 0, (
        f"pm_board({filter_kwargs}) must make no Store.get calls; got {counts['get']}"
    )
    assert counts["list_tasks_with_bodies"] == 1, (
        f"pm_board({filter_kwargs}) must call Store.list_tasks_with_bodies "
        f"exactly once (US-PRJ-43-5); got {counts['list_tasks_with_bodies']}"
    )
    assert counts["list_tasks"] == 0, (
        f"pm_board({filter_kwargs}) must not call Store.list_tasks on top of "
        f"its one list_tasks_with_bodies (US-PRJ-43-6); got {counts['list_tasks']}"
    )
    assert counts["list_stories"] == 1, (
        f"pm_board({filter_kwargs}) must call Store.list_stories exactly "
        f"once, not per task (US-PRJ-43-6); got {counts['list_stories']}"
    )

    # Non-trivial output: the filter really narrowed the board to the group
    # named above, and left every other group empty.
    expected = dict.fromkeys(
        ("available", "not_ready", "in_progress", "in_review", "blocked"), 0
    )
    expected.update(expected_summary)
    assert data["summary"] == expected


def test_pm_epic_partitions_ten_stories_from_one_task_listing(n1_project, store_spy):
    """pm_epic over a 10-story epic reads the task list exactly once.

    Guards US-PRJ-43-7.  The fixture spreads its stories over three epics, so
    the test first re-points all ten at the first epic — an epic large enough
    that a per-story ``list_tasks(story_id=...)`` is unmistakable in the count.
    """
    from projectman.server import pm_epic, pm_update

    epic_id = n1_project["epic_ids"][0]
    for story_id in n1_project["story_ids"]:
        pm_update(story_id, epic_id=epic_id)

    store_spy.reset()
    data = yaml.safe_load(pm_epic(epic_id, limit=N1_STORIES))

    counts = store_spy.counts
    assert counts["list_tasks"] == 1, (
        "pm_epic must call Store.list_tasks exactly once and partition by "
        f"story_id in memory (US-PRJ-43-7); got {counts['list_tasks']} calls "
        f"for {N1_STORIES} stories"
    )
    call = store_spy.calls_to("list_tasks")[0]
    assert (call.args, call.kwargs) == ((), {}), (
        "pm_epic's single Store.list_tasks call must be unfiltered, not "
        f"per-story (US-PRJ-43-7); got args={call.args} kwargs={call.kwargs}"
    )
    assert counts["list_stories"] == 1, (
        f"pm_epic must call Store.list_stories exactly once; got {counts['list_stories']}"
    )
    assert counts["get_task"] == 0, (
        f"pm_epic must not call Store.get_task per task; got {counts['get_task']}"
    )
    assert counts["get_story"] == 0, (
        "pm_epic must not call Store.get_story per linked story; got "
        f"{counts['get_story']}"
    )

    # Non-trivial output: all ten stories, each with its own ten tasks, and a
    # rollup that excludes the archived ones.
    assert data["rollup"]["story_count"] == N1_STORIES
    # list_stories orders by id lexically, so US-TST-10 sorts next to US-TST-1.
    assert sorted(s["id"] for s in data["stories"]) == sorted(n1_project["story_ids"])
    assert all(len(s["tasks"]) == N1_TASKS_PER_STORY for s in data["stories"])
    assert data["rollup"]["total_points"] > 0


def test_pm_search_tag_filter_reads_metadata_in_two_listings(
    n1_project, store_spy, monkeypatch
):
    """pm_search's tag filter batches metadata — no Store.get per hit.

    Guards US-PRJ-43-8.  The embeddings module is stubbed so the test neither
    needs numpy nor a built index: what is under test is the post-filter that
    used to call ``store.get(r.id)`` once per result (and swallow the raise
    for an id no longer on disk).
    """
    import sys

    from projectman.server import pm_search

    # Twenty hits — every story plus one task from each — so a per-result
    # get() would be twenty calls, not a rounding error.
    hits = []
    for n in range(1, N1_STORIES + 1):
        hits.append(
            {"id": f"US-TST-{n}", "title": f"Story {n}", "type": "story", "score": 0.9}
        )
        hits.append(
            {
                "id": f"US-TST-{n}-1",
                "title": f"Task 1 of story {n}",
                "type": "task",
                "score": 0.8,
            }
        )
    # An id that is not on disk: it must drop out of the filtered results
    # without anyone calling get() on it.
    hits.append({"id": "US-TST-99", "title": "Gone", "type": "story", "score": 0.7})
    monkeypatch.setitem(
        sys.modules, "projectman.embeddings", _fake_embedding_module(hits)
    )

    store_spy.reset()
    data = yaml.safe_load(pm_search("zzqqxx", tag="api"))

    counts = store_spy.counts
    assert counts["get"] == 0, (
        "pm_search's tag filter must not call Store.get per result "
        f"(US-PRJ-43-8); got {counts['get']} calls for {len(hits)} hits"
    )
    assert counts["get_story"] == 0 and counts["get_task"] == 0, (
        "pm_search's tag filter must not fetch hits individually "
        f"(US-PRJ-43-8); got {store_spy.nonzero()}"
    )
    assert counts["list_stories"] == 1, (
        "pm_search's tag filter must list stories exactly once, not per hit "
        f"(US-PRJ-43-8); got {counts['list_stories']}"
    )
    assert counts["list_tasks"] == 1, (
        "pm_search's tag filter must list tasks exactly once, not per hit "
        f"(US-PRJ-43-8); got {counts['list_tasks']}"
    )

    # Non-trivial output: only the api-tagged items survive, in ranking order,
    # and the stubbed branch really ran (keyword results carry a snippet;
    # embedding results do not, and "zzqqxx" matches no file anyway).
    assert data, "the stubbed embeddings branch did not run"
    assert all("snippet" not in item for item in data), data
    assert [item["id"] for item in data] == [
        "US-TST-4",
        "US-TST-4-1",
        "US-TST-5",
        "US-TST-5-1",
    ], data
    assert set(N1_TAGGED_TASK_IDS) <= {item["id"] for item in data}


def test_pm_search_keyword_path_reads_no_store_items(
    n1_project, store_spy, monkeypatch
):
    """The keyword fallback filters by tag while it scans — no Store reads.

    The companion to the embeddings test: ``keyword_search`` walks the files
    itself, so the tag filter costs nothing per hit here either.  Stubbing
    ``search()`` to return no hits is what forces the fallback.
    """
    import sys

    from projectman.server import pm_search

    monkeypatch.setitem(
        sys.modules, "projectman.embeddings", _fake_embedding_module([])
    )

    store_spy.reset()
    data = yaml.safe_load(pm_search("handler", tag="api"))

    assert store_spy.nonzero() == {}, (
        "pm_search's keyword path must not read items through the Store "
        f"(US-PRJ-43-8); got {store_spy.nonzero()}"
    )
    # Non-trivial output: "handler" appears in every task body, so the tag is
    # what narrows 100 tasks down to the two tagged ones.
    assert sorted(item["id"] for item in data) == sorted(N1_TAGGED_TASK_IDS), data


def test_pm_active_lists_stories_once_with_a_tag(n1_project, store_spy):
    """pm_active reuses its one story listing for the tag's parent lookup.

    Guards US-PRJ-43-8's second half: the tag branch used to call
    ``list_stories()`` a second time to resolve each task's parent story.
    """
    from projectman.server import pm_active, pm_update

    # Give the tag filter something to keep and something to drop: a tagged
    # task under a tagged story, and an in-progress task with no tag at all.
    pm_update("US-TST-4-1", status="in-progress", assignee="claude")
    pm_update("US-TST-6-1", status="in-progress", assignee="claude")

    store_spy.reset()
    data = yaml.safe_load(pm_active(tag="api"))

    counts = store_spy.counts
    assert counts["list_stories"] == 1, (
        "pm_active must call Store.list_stories exactly once — the tag "
        "branch reuses that listing instead of loading a second "
        f"(US-PRJ-43-8); got {counts['list_stories']}"
    )
    assert counts["list_tasks"] == 1, (
        f"pm_active must call Store.list_tasks exactly once; got {counts['list_tasks']}"
    )
    assert counts["get_story"] == 0, (
        "pm_active must not call Store.get_story per in-progress task "
        f"(US-PRJ-43-8); got {counts['get_story']}"
    )

    # Non-trivial output: the two api-tagged stories, and only the tagged task.
    assert [s["id"] for s in data["active_stories"]] == ["US-TST-4", "US-TST-5"]
    assert data["active_stories_total"] == 2
    assert [t["id"] for t in data["active_tasks"]] == ["US-TST-4-1"]
    assert data["active_tasks_total"] == 1
