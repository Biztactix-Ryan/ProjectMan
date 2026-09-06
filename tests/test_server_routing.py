"""ID-prefix store routing — ``server._store_for_id`` / ``_stores_for_ids``.

US-PM-34-6.  The resolver only; no tool routes through it yet (US-PM-34-7).

Covers:
- ``_prefix_of`` on all four ID shapes and on malformed input;
- single-project mode returning the one store whatever the prefix says;
- hub mode resolving each ID kind to the subproject that owns the prefix,
  and the hub's own prefix to ``{root}/.project``;
- the Store objects being the very ones ``_store()`` hands out (shared cache);
- unknown prefix, unattached store and duplicate prefix, each with the code
  US-PM-34-7 will branch on;
- ``_stores_for_ids`` grouping order and its all-or-nothing failure.
"""

import pytest

from projectman.errors import ConflictError, NotFoundError, ValidationError
from projectman.server import (
    _prefix_of,
    _store,
    _store_cache,
    _store_for_id,
    _stores_for_ids,
)

from conftest import make_hub_subproject, make_unattached_hub_subproject


@pytest.fixture
def single(tmp_project, monkeypatch):
    """Single-project mode (prefix TST) pinned as the process's root."""
    monkeypatch.chdir(tmp_project)
    _store_cache.clear()
    yield tmp_project
    _store_cache.clear()


@pytest.fixture
def hub(tmp_hub, monkeypatch):
    """A hub (prefix HUB) with two attached subprojects: API and WEB."""
    make_hub_subproject(tmp_hub, "api", "API")
    make_hub_subproject(tmp_hub, "web", "WEB")
    monkeypatch.chdir(tmp_hub)
    _store_cache.clear()
    yield tmp_hub
    _store_cache.clear()


# ─── _prefix_of ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "item_id,expected",
    [
        ("US-TST-1", "TST"),           # story
        ("US-TST-1-2", "TST"),         # task — same prefix, different suffix
        ("EPIC-TST-3", "TST"),         # epic
        ("SPRINT-TST-4", "TST"),       # sprint
        ("US-A-1", "A"),               # single-letter prefix
        ("US-PM2-10-11", "PM2"),       # digits allowed after the first letter
    ],
)
def test_prefix_of_reads_every_id_shape(item_id, expected):
    assert _prefix_of(item_id) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "us-tst-1",       # lowercase
        "US-tst-1",       # lowercase prefix
        "US-TST",         # missing the number
        "TST-1",          # missing the kind
        "US--1",          # empty prefix
        "US-TST-1-",      # trailing dash
        "US-TST-1-2-3",   # too many segments
        "STORY-TST-1",    # unknown kind
        "",
        None,
        123,
    ],
)
def test_prefix_of_rejects_malformed_ids(bad):
    with pytest.raises(ValidationError) as exc:
        _prefix_of(bad)
    assert "malformed id" in str(exc.value)
    assert exc.value.code == "invalid"


# ─── Single-project mode ─────────────────────────────────────────


@pytest.mark.parametrize(
    "item_id", ["US-TST-1", "US-TST-1-2", "EPIC-TST-1", "SPRINT-TST-1"]
)
def test_single_mode_returns_the_one_store(single, item_id):
    assert _store_for_id(item_id) is _store()


def test_single_mode_ignores_a_foreign_prefix(single):
    """Behaviour today never checks the prefix; US-PM-34-5 pins that."""
    assert _store_for_id("US-OTHER-9") is _store()
    assert _store_for_id("US-OTHER-9").project_dir == single / ".project"


def test_single_mode_still_rejects_a_malformed_id(single):
    with pytest.raises(ValidationError):
        _store_for_id("nonsense")


# ─── Hub mode ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "item_id", ["US-API-1", "US-API-1-2", "EPIC-API-1", "SPRINT-API-1"]
)
def test_hub_resolves_every_id_kind_to_the_owning_subproject(hub, item_id):
    store = _store_for_id(item_id)
    assert store.project_dir == hub / "projects" / "api" / ".project"


def test_hub_routes_each_prefix_to_its_own_subproject(hub):
    assert _store_for_id("US-API-1").project_dir == (
        hub / "projects" / "api" / ".project"
    )
    assert _store_for_id("US-WEB-1").project_dir == (
        hub / "projects" / "web" / ".project"
    )


def test_hub_own_prefix_resolves_to_the_hub_store(hub):
    store = _store_for_id("US-HUB-1")
    assert store.project_dir == hub / ".project"
    assert store is _store()


def test_resolved_store_is_the_cached_store_object(hub):
    """One Store object per store directory, whichever door you come in by."""
    from projectman.server import _store_for_prefix

    assert _store_for_id("US-API-1") is _store_for_prefix("API")
    assert _store_for_id("US-API-1") is _store_for_id("EPIC-API-7")
    assert _store_for_id("US-API-1") is not _store_for_id("US-WEB-1")


def test_unknown_prefix_lists_the_known_ones(hub):
    with pytest.raises(NotFoundError) as exc:
        _store_for_id("US-NOPE-1")
    message = str(exc.value)
    assert exc.value.code == "not_found"
    assert "NOPE" in message
    # Sorted, and the hub's own prefix is one of them.
    assert "API, HUB, WEB" in message


def test_unattached_store_is_not_opened_and_says_how_to_attach(tmp_hub, monkeypatch):
    make_hub_subproject(tmp_hub, "api", "API")
    make_unattached_hub_subproject(tmp_hub, "ops", "OPS")
    monkeypatch.chdir(tmp_hub)
    _store_cache.clear()

    with pytest.raises(NotFoundError) as exc:
        _store_for_id("US-OPS-1")
    message = str(exc.value)
    assert exc.value.code == "not_found"
    assert "ops" in message
    assert "add-project" in message and "migrate-hub" in message
    # Nothing was constructed for it.
    assert (tmp_hub / "projects" / "ops" / ".project") not in _store_cache
    # The attached sibling still resolves.
    assert _store_for_id("US-API-1").project_dir == (
        tmp_hub / "projects" / "api" / ".project"
    )
    _store_cache.clear()


def test_duplicate_prefix_names_both_projects(tmp_hub, monkeypatch):
    make_hub_subproject(tmp_hub, "api", "DUP")
    make_hub_subproject(tmp_hub, "web", "DUP")
    monkeypatch.chdir(tmp_hub)
    _store_cache.clear()

    with pytest.raises(ConflictError) as exc:
        _store_for_id("US-DUP-1")
    message = str(exc.value)
    assert exc.value.code == "conflict"
    assert "api" in message and "web" in message
    _store_cache.clear()


def test_duplicate_with_the_hub_prefix_is_also_a_conflict(tmp_hub, monkeypatch):
    make_hub_subproject(tmp_hub, "api", "HUB")
    monkeypatch.chdir(tmp_hub)
    _store_cache.clear()

    with pytest.raises(ConflictError):
        _store_for_id("US-HUB-1")
    _store_cache.clear()


def test_hub_rejects_a_malformed_id_before_looking_anything_up(hub):
    with pytest.raises(ValidationError) as exc:
        _store_for_id("us-api-1")
    assert exc.value.code == "invalid"


# ─── _stores_for_ids ─────────────────────────────────────────────


def test_grouping_preserves_first_seen_store_order(hub):
    groups = _stores_for_ids(
        ["US-WEB-1", "US-API-2", "US-WEB-3-1", "EPIC-API-4", "US-WEB-5"]
    )
    assert [ids for _store_obj, ids in groups] == [
        ["US-WEB-1", "US-WEB-3-1", "US-WEB-5"],
        ["US-API-2", "EPIC-API-4"],
    ]
    assert groups[0][0] is _store_for_id("US-WEB-1")
    assert groups[1][0] is _store_for_id("US-API-2")


def test_grouping_in_single_mode_is_one_group(single):
    groups = _stores_for_ids(["US-TST-1", "EPIC-OTHER-2", "US-TST-3-1"])
    assert len(groups) == 1
    store, ids = groups[0]
    assert store is _store()
    assert ids == ["US-TST-1", "EPIC-OTHER-2", "US-TST-3-1"]


def test_grouping_of_no_ids_is_empty(hub):
    assert _stores_for_ids([]) == []


def test_one_bad_id_fails_the_whole_grouping(hub):
    with pytest.raises(NotFoundError):
        _stores_for_ids(["US-API-1", "US-NOPE-2", "US-WEB-3"])
    with pytest.raises(ValidationError):
        _stores_for_ids(["US-API-1", "garbage"])
