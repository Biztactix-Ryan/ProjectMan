"""ID handling and single-store answers — ``server._store_for_id`` / ``_stores_for_ids``.

US-PM-34-6, narrowed to one store by US-PM-44.  There is no hub and no prefix
routing: every well-formed ID resolves to the one store the server was started
in, and the resolver's only job is to reject a malformed ID before it reaches
the store.

Covers:
- ``_prefix_of`` on all four ID shapes and on malformed input;
- ``_store_for_id`` returning the one store whatever the prefix says, and
  still raising ``invalid`` for a malformed ID;
- ``_stores_for_ids`` grouping everything into that single group, and failing
  the whole grouping on one malformed ID;
- the six read tools that used to roll a hub up answering for the single store
  with no ``subprojects``, ``by_project`` or ``not_attached`` key.
"""

import pytest
import yaml

from projectman.errors import ValidationError
from projectman.server import (
    _prefix_of,
    _store,
    _store_cache,
    _store_for_id,
    _stores_for_ids,
)


@pytest.fixture
def single(tmp_project, monkeypatch):
    """Single-project mode (prefix TST) pinned as the process's root."""
    monkeypatch.chdir(tmp_project)
    _store_cache.clear()
    yield tmp_project
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


# ─── One store, whatever the ID says ─────────────────────────────


@pytest.mark.parametrize(
    "item_id", ["US-TST-1", "US-TST-1-2", "EPIC-TST-1", "SPRINT-TST-1"]
)
def test_every_id_kind_returns_the_one_store(single, item_id):
    assert _store_for_id(item_id) is _store()


def test_a_foreign_prefix_still_returns_the_one_store(single):
    """The prefix is never looked up — a single-project install never did."""
    assert _store_for_id("US-OTHER-9") is _store()
    assert _store_for_id("US-OTHER-9").project_dir == single / ".project"


def test_a_malformed_id_is_still_rejected(single):
    with pytest.raises(ValidationError) as exc:
        _store_for_id("nonsense")
    assert exc.value.code == "invalid"


def test_the_resolved_store_is_the_cached_store_object(single):
    """One Store object for the process, whichever door you come in by."""
    assert _store_for_id("US-TST-1") is _store_for_id("EPIC-OTHER-7")
    assert _store_for_id("US-TST-1") is _store()


# ─── _stores_for_ids ─────────────────────────────────────────────


def test_grouping_is_always_one_group(single):
    groups = _stores_for_ids(["US-TST-1", "EPIC-OTHER-2", "US-TST-3-1"])
    assert len(groups) == 1
    store, ids = groups[0]
    assert store is _store()
    assert ids == ["US-TST-1", "EPIC-OTHER-2", "US-TST-3-1"]


def test_grouping_of_no_ids_is_empty(single):
    assert _stores_for_ids([]) == []


def test_one_malformed_id_fails_the_whole_grouping(single):
    with pytest.raises(ValidationError):
        _stores_for_ids(["US-TST-1", "garbage"])


# ─── No hub keys in any answer (US-PM-44) ────────────────────────


#: The keys a hub rollup used to add.  None of them may appear in any tool's
#: response now that there is one store.
_HUB_KEYS = ("subprojects", "by_project", "not_attached")


def _assert_no_hub_keys(payload) -> None:
    """No hub key anywhere in the response, at any nesting depth."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in _HUB_KEYS, f"hub key {key!r} in the response"
            _assert_no_hub_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_hub_keys(item)


def test_read_tools_carry_no_hub_keys(single):
    """pm_status, pm_epic, pm_burndown, pm_malformed and pm_context."""
    from projectman.server import (
        pm_burndown,
        pm_context,
        pm_create_epic,
        pm_create_story,
        pm_epic,
        pm_malformed,
        pm_status,
    )

    pm_create_epic("An epic", "Body")
    pm_create_story("A story", "Body", points=5, epic_id="EPIC-TST-1")

    for call in (
        pm_status,
        pm_burndown,
        pm_malformed,
        pm_context,
        lambda: pm_epic("EPIC-TST-1"),
    ):
        data = yaml.safe_load(call())
        _assert_no_hub_keys(data)


def test_pm_git_status_carries_no_hub_keys(tmp_git_project, monkeypatch):
    """pm_git_status answers for the one store it is standing in."""
    monkeypatch.chdir(tmp_git_project)
    _store_cache.clear()
    from projectman.server import pm_git_status

    data = yaml.safe_load(pm_git_status())
    _assert_no_hub_keys(data)
    _store_cache.clear()
