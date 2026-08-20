"""Compare-and-swap claiming (US-PM-7-7).

Implements §2 of docs/reference/claim-release-contract.md: claiming compares
the **on-disk** assignee and status inside an exclusive lock on the task file,
so two concurrent workers can never both win.  The loser is an *expected
negative* (`status: already_claimed`, carrying the current `holder`), never an
error, and the task it lost is left byte-for-byte untouched.

The idempotent re-claim from commit 2261a0d — the holder re-grabbing its own
todo/in-progress task — is load-bearing for the pm_done_next hand-off and is
asserted here at both layers so the CAS cannot silently drop it.
"""

import importlib.util
import threading
import time
from pathlib import Path

import pytest
import yaml

import projectman
from projectman.store import Store

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _task(store: Store, n_tasks: int = 1) -> Store:
    """A story with `n_tasks` ready tasks, all todo and unassigned."""
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active")
    for i in range(1, n_tasks + 1):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    return store


# ─── Store.claim_task — the primitive ────────────────────────────


def test_claim_task_winner_takes_the_task(store):
    _task(store)
    won, meta = store.claim_task("US-TST-1-1", "worker-1")
    assert won is True
    assert meta.assignee == "worker-1"
    assert meta.status.value == "in-progress"
    # ...and it is durable, not just returned
    on_disk, _ = Store(store.root).get_task("US-TST-1-1")
    assert on_disk.assignee == "worker-1"


def test_claim_task_loser_gets_the_current_holder(store):
    _task(store)
    store.claim_task("US-TST-1-1", "worker-1")
    won, meta = store.claim_task("US-TST-1-1", "worker-2")
    assert won is False
    assert meta.assignee == "worker-1"


def test_claim_task_loser_leaves_the_task_untouched(store):
    _task(store)
    store.claim_task("US-TST-1-1", "worker-1")
    path = store.tasks_dir / "US-TST-1-1.md"
    before = path.read_bytes()
    won, _ = store.claim_task("US-TST-1-1", "worker-2")
    assert won is False
    assert path.read_bytes() == before


def test_claim_task_same_assignee_reclaim_is_idempotent(store):
    """The pm_done_next hand-off: pre-claimed, then re-claimed by its holder."""
    _task(store)
    store.claim_task("US-TST-1-1", "claude")
    won, meta = store.claim_task("US-TST-1-1", "claude")
    assert won is True
    assert meta.assignee == "claude"
    assert meta.status.value == "in-progress"


def test_claim_task_reclaims_own_task_reset_to_todo(store):
    _task(store)
    store.claim_task("US-TST-1-1", "claude")
    store.update("US-TST-1-1", status="todo")
    won, meta = store.claim_task("US-TST-1-1", "claude")
    assert won is True
    assert meta.status.value == "in-progress"


@pytest.mark.parametrize("status", ["review", "done", "blocked"])
def test_claim_task_compares_status_not_only_assignee(store, status):
    """A task that moved past todo is unclaimable even with no assignee."""
    _task(store)
    store.update("US-TST-1-1", status=status)
    won, meta = store.claim_task("US-TST-1-1", "worker-1")
    assert won is False
    assert meta.status.value == status


def test_claim_task_rejects_own_reclaim_of_a_finished_task(store):
    _task(store)
    store.claim_task("US-TST-1-1", "claude")
    store.update("US-TST-1-1", status="done")
    won, _ = store.claim_task("US-TST-1-1", "claude")
    assert won is False


def test_claim_task_expected_assignee_narrows_the_compare(store):
    """Explicit hand-off: win only when the named holder still holds it."""
    _task(store)
    store.claim_task("US-TST-1-1", "worker-1")

    lost, meta = store.claim_task(
        "US-TST-1-1", "worker-2", expected_assignee="somebody-else"
    )
    assert lost is False
    assert meta.assignee == "worker-1"

    won, meta = store.claim_task(
        "US-TST-1-1", "worker-2", expected_assignee="worker-1"
    )
    assert won is True
    assert meta.assignee == "worker-2"


def test_claim_task_bypasses_the_process_cache(store):
    """The compare must read disk: get_task will serve a stale cached copy."""
    from projectman.store import _cache, _cache_mtimes

    _task(store)
    store.list_tasks()  # populate the module-level cache while still unclaimed
    key = store._cache_key("tasks")
    unclaimed = list(_cache[key])

    store.claim_task("US-TST-1-1", "worker-1")

    # Poison the cache with the pre-claim state, marked fresh — exactly what a
    # long-lived server process holds when another worker claims underneath it.
    _cache[key] = unclaimed
    _cache_mtimes[key] = store._get_dir_mtime(store.tasks_dir)
    assert store.get_task("US-TST-1-1")[0].assignee is None, "cache is not stale"

    won, meta = store.claim_task("US-TST-1-1", "worker-2")
    assert won is False, "claimed over a holder the cache had not heard about"
    assert meta.assignee == "worker-1"


def test_claim_task_missing_task_raises(store):
    _task(store)
    with pytest.raises(FileNotFoundError):
        store.claim_task("US-TST-1-99", "worker-1")


# ─── Concurrency — the acceptance criterion ──────────────────────


def test_concurrent_claims_produce_exactly_one_winner(store):
    """Eight workers race for one task; exactly one may win."""
    _task(store)
    workers = [f"worker-{i}" for i in range(8)]
    barrier = threading.Barrier(len(workers))
    results: dict[str, tuple[bool, str | None]] = {}
    lock = threading.Lock()

    def race(name: str) -> None:
        own_store = Store(store.root)
        barrier.wait()
        won, meta = own_store.claim_task("US-TST-1-1", name)
        with lock:
            results[name] = (won, meta.assignee)

    threads = [threading.Thread(target=race, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "claim deadlocked"

    winners = [name for name, (won, _) in results.items() if won]
    assert len(winners) == 1, f"expected one winner, got {winners}"

    # Every loser was told who actually holds it, and the file agrees.
    losers = {name: holder for name, (won, holder) in results.items() if not won}
    assert set(losers.values()) == {winners[0]}
    on_disk, _ = Store(store.root).get_task("US-TST-1-1")
    assert on_disk.assignee == winners[0]
    assert on_disk.status.value == "in-progress"


def test_claim_serialises_read_verify_write(store, monkeypatch):
    """The lock, not luck, is what makes the swap safe.

    A delay is injected *after* the on-disk read and *inside* the critical
    section.  Unlocked, the second worker reads the same unclaimed file during
    that window and both win — this test fails with the lock removed (verified
    by degrading `_exclusive_file_lock` to a no-op).  Locked, the second
    worker waits, re-reads, and sees the first worker's claim.
    """
    import time

    _task(store)
    real_compare = Store.__dict__["_claim_won"].__func__

    def slow_compare(disk, assignee, expected_assignee):
        time.sleep(0.3)
        return real_compare(disk, assignee, expected_assignee)

    monkeypatch.setattr(Store, "_claim_won", staticmethod(slow_compare))

    barrier = threading.Barrier(2)
    results: dict[str, bool] = {}
    lock = threading.Lock()

    def race(name: str) -> None:
        own_store = Store(store.root)
        barrier.wait()
        won, _ = own_store.claim_task("US-TST-1-1", name)
        with lock:
            results[name] = won

    threads = [
        threading.Thread(target=race, args=(n,)) for n in ("worker-a", "worker-b")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sum(results.values()) == 1, results


def test_concurrent_claims_on_different_tasks_all_win(store):
    """The lock is per task file — separate tasks must not contend."""
    _task(store, n_tasks=4)
    barrier = threading.Barrier(4)
    results: dict[str, bool] = {}
    lock = threading.Lock()

    def race(i: int) -> None:
        own_store = Store(store.root)
        barrier.wait()
        won, _ = own_store.claim_task(f"US-TST-1-{i}", f"worker-{i}")
        with lock:
            results[f"US-TST-1-{i}"] = won

    threads = [threading.Thread(target=race, args=(i,)) for i in range(1, 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(results.values()), results


_CHILD_CLAIM = """
import pathlib, sys, time
root, task_id, name, gofile = sys.argv[1:5]
from projectman.store import Store
# Widen the critical section so the siblings genuinely overlap: this child
# holds the flock for the sleep, and every other child must wait on it.
real = Store.__dict__["_claim_won"].__func__
def slow(disk, assignee, expected_assignee):
    time.sleep(0.5)
    return real(disk, assignee, expected_assignee)
Store._claim_won = staticmethod(slow)
go = pathlib.Path(gofile)
while not go.exists():
    time.sleep(0.005)
won, meta = Store(pathlib.Path(root)).claim_task(task_id, name)
print("%d %s" % (int(won), meta.assignee), flush=True)
"""


@pytest.mark.skipif(
    importlib.util.find_spec("fcntl") is None,
    reason="flock is POSIX-only; the CAS degrades to a single-process guarantee",
)
def test_concurrent_claims_across_processes_produce_one_winner(store, tmp_path):
    """Four separate interpreters race for one task; exactly one may win.

    The thread races above all share one interpreter, so they also share the
    module-level cache and the GIL.  ``flock`` was chosen precisely because it
    holds *between processes* — the deployed shape, where each worker runs its
    own server process — so the criterion is only really pinned once the
    contenders are real processes with independent caches.

    It also pins the subtle half of the contract: the winner replaces the path
    with a new inode, so a loser that was blocked on the *old* inode must still
    re-read by path and see the winner's name.  Reading through the lock's own
    descriptor would let every loser report ``holder=None`` here.
    """
    import os
    import subprocess
    import sys

    _task(store)
    script = tmp_path / "child_claim.py"
    script.write_text(_CHILD_CLAIM)
    gofile = tmp_path / "go"

    env = dict(os.environ)
    src = str(Path(projectman.__file__).parent.parent)
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")

    names = [f"proc-{i}" for i in range(4)]
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(store.root), "US-TST-1-1", n, str(gofile)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for n in names
    ]
    time.sleep(1.5)  # let every child finish importing and reach the go-poll
    gofile.write_text("go")

    results = {}
    for name, p in zip(names, procs):
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, f"{name} failed: {err}"
        won, holder = out.strip().split(" ", 1)
        results[name] = (won == "1", holder)

    winners = [n for n, (won, _) in results.items() if won]
    assert len(winners) == 1, f"expected one winner, got {winners}: {results}"

    # Every loser re-read by path and saw the winner's write — not None, and
    # not its own name.
    losers = {n: holder for n, (won, holder) in results.items() if not won}
    assert set(losers.values()) == {winners[0]}, losers

    on_disk, _ = Store(store.root).get_task("US-TST-1-1")
    assert on_disk.assignee == winners[0]
    assert on_disk.status.value == "in-progress"


def test_concurrent_pm_grab_yields_one_grab_and_expected_negatives(tmp_project):
    """End to end through the tool: one `grabbed`, the rest `already_claimed`."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )

    workers = [f"worker-{i}" for i in range(6)]
    barrier = threading.Barrier(len(workers))
    payloads: dict[str, dict] = {}
    lock = threading.Lock()

    def race(name: str) -> None:
        barrier.wait()
        result = yaml.safe_load(pm_grab("US-TST-1-1", assignee=name))
        with lock:
            payloads[name] = result

    threads = [threading.Thread(target=race, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "pm_grab deadlocked"

    grabbed = [n for n, p in payloads.items() if "grabbed" in p]
    assert len(grabbed) == 1, f"expected one winner, got {grabbed}"

    for name, payload in payloads.items():
        if name in grabbed:
            continue
        # A loser is never an error — it either failed readiness (it saw the
        # winner's claim before it tried) or lost the swap.  Both are
        # expected negatives naming the holder.
        assert payload["outcome"] == "expected_negative"
        assert payload["status"] in ("already_claimed", "not_ready")
        if payload["status"] == "already_claimed":
            assert payload["holder"] == grabbed[0]


# ─── pm_grab — the already_claimed expected negative ─────────────


@pytest.fixture
def readiness_always_passes(monkeypatch):
    """Force the advisory readiness check to pass, isolating the CAS.

    Readiness runs outside the lock and normally catches an already-assigned
    task first.  The race this task exists to close is the window *after* it
    passes, which is what this reproduces deterministically.
    """
    import projectman.readiness as readiness

    monkeypatch.setattr(
        readiness,
        "check_readiness",
        lambda *a, **k: {"ready": True, "blockers": [], "warnings": []},
    )


def test_pm_grab_loser_gets_already_claimed_with_holder(
    tmp_project, readiness_always_passes
):
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    yaml.safe_load(pm_grab("US-TST-1-1", assignee="worker-1"))

    body = pm_grab("US-TST-1-1", assignee="worker-2")
    result = yaml.safe_load(body)

    # Successful response, not a failure — the whole point of US-PM-2.
    assert not body.startswith("error:")
    assert result["outcome"] == "expected_negative"
    assert result["status"] == "already_claimed"
    assert result["message"] == "task is already claimed"
    assert result["holder"] == "worker-1"
    assert result["task_id"] == "US-TST-1-1"
    assert "grabbed" not in result


def test_pm_grab_loser_leaves_the_task_untouched(tmp_project, readiness_always_passes):
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    pm_grab("US-TST-1-1", assignee="worker-1")
    path = tmp_project / ".project" / "tasks" / "US-TST-1-1.md"
    before = path.read_bytes()

    pm_grab("US-TST-1-1", assignee="worker-2")
    assert path.read_bytes() == before


def test_pm_grab_winner_shape_is_unchanged(tmp_project):
    """The CAS is invisible to a caller that wins — no new success field."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    result = yaml.safe_load(pm_grab("US-TST-1-1"))
    grabbed = result["grabbed"]
    assert set(grabbed) <= {
        "task",
        "body",
        "story_context",
        "sibling_tasks",
        "sibling_tasks_total",
        "sibling_tasks_done",
        "dependency_status",
        "warnings",
    }
    assert grabbed["task"]["assignee"] == "claude"
    assert grabbed["task"]["status"] == "in-progress"


def test_pm_grab_reclaim_still_wins_under_the_cas(tmp_project):
    """Regression guard for 2261a0d — the hand-off must survive the CAS."""
    from projectman.server import pm_create_story, pm_create_tasks, pm_grab, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1", [{"title": "Task 1", "description": READY_BODY, "points": 1}]
    )
    first = yaml.safe_load(pm_grab("US-TST-1-1"))
    again = yaml.safe_load(pm_grab("US-TST-1-1"))
    assert "grabbed" in first and "grabbed" in again
    assert again["grabbed"]["task"]["assignee"] == "claude"
