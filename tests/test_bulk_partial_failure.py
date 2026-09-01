"""The partial-failure contract shared by the bulk write verbs (US-PM-12-8).

The story's scenario, literally: *a bulk call touching 50 items where 3 fail
must report which succeeded and which did not, without rolling back the
successes or hiding the failures.*  It is exercised here end to end, over a
real ``tools/call``, for both `pm_update_many` (US-PM-12-6) and
`pm_archive_many` (US-PM-12-7) — 50 IDs, 3 of them bad, sitting at the first,
a middle and the last position so that neither an early nor a late failure can
truncate the sweep.

The rest of the file pins the contract itself rather than either verb's own
behaviour: which keys exist and of what type, which keys are present *only* on
a partial failure, where the line runs between a malformed **call** (rejected
whole, nothing written, ``is_error`` set) and a failing **item** (soft, named,
the rest still landing), that a partial failure is never a failed call, and
that the retry a caller is told to perform — re-issue with the ``failed`` IDs
only — actually works.

`tests/test_bulk_update.py` and `tests/test_bulk_archive.py` cover each verb's
own surface; this file is the one place the two are held to the *same* words,
alongside `_bulk_result` in `projectman.server` (the single code path that
builds the shape) and the "Partial failure" section of
`docs/reference/mcp-tools.md`.
"""

from pathlib import Path

import anyio
import mcp.types as types
import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.store import Store

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)

#: How many real items the story's scenario writes, and how many bad IDs ride
#: along with them.  47 + 3 = the 50 the story names.
REAL_ITEMS = 47
BAD_ITEMS = 3


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


@pytest.fixture
def fifty(tmp_project) -> tuple[list[str], list[str], list[str]]:
    """The story's list: 47 real task IDs and 3 that do not exist, interleaved.

    Returns ``(ids, real, missing)`` where ``ids`` is the 50-item call list
    with the bad IDs at the **first, a middle and the last** position, and
    ``real`` is the 47 successes in the order the call lists them.
    """
    from projectman.server import pm_create_story, pm_create_tasks, pm_update

    pm_create_story("Story", "Story body text long enough to matter.")
    pm_update("US-TST-1", status="active")
    pm_create_tasks(
        "US-TST-1",
        [
            {"title": f"Task {i}", "description": READY_BODY, "points": 1}
            for i in range(1, REAL_ITEMS + 1)
        ],
    )
    real = [f"US-TST-1-{i}" for i in range(1, REAL_ITEMS + 1)]
    # The three that will fail are the next IDs the project would hand out, so
    # the retry test can make them real and re-issue the same list.
    missing = [f"US-TST-1-{i}" for i in range(REAL_ITEMS + 1, REAL_ITEMS + 1 + BAD_ITEMS)]

    ids = [missing[0]] + real[:24] + [missing[1]] + real[24:] + [missing[2]]
    assert len(ids) == 50
    assert ids[0] == missing[0] and ids[-1] == missing[2] and ids[25] == missing[1]
    return ids, real, missing


def _fresh_store(tmp_project) -> Store:
    """A Store reading straight from disk, so nothing is answered from cache."""
    from projectman.store import clear_all_caches

    clear_all_caches()
    return Store(tmp_project)


def _statuses(tmp_project, item_ids: list[str]) -> dict[str, str]:
    store = _fresh_store(tmp_project)
    return {i: store.get(i)[0].status.value for i in item_ids}


def _archived_flags(tmp_project, item_ids: list[str]) -> dict[str, bool]:
    store = _fresh_store(tmp_project)
    out = {}
    for i in item_ids:
        meta, _ = store.get(i)
        out[i] = bool(getattr(meta, "archived", False)) or meta.status.value == "archived"
    return out


def _item_files(tmp_project, item_ids: list[str]) -> dict[str, tuple]:
    """Each item's file on disk: ``{id: (relative path, mtime_ns, bytes)}``.

    Compared before and after a call, this catches a write the reported result
    never mentions.  ``mtime_ns`` is in there because the item files stamp
    ``updated`` as a *date*: a re-write on the same day can leave the bytes
    identical, and only the mtime shows the file was touched at all.
    """
    root = Path(tmp_project) / ".project"
    out: dict[str, tuple] = {}
    for item_id in item_ids:
        matches = [p for p in root.rglob(f"{item_id}.md") if p.is_file()]
        assert len(matches) == 1, f"{item_id}: {matches}"
        path = matches[0]
        out[item_id] = (
            str(path.relative_to(root)),
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
    return out


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


def _sweep(name: str, arguments: dict) -> tuple[bool, dict]:
    is_error, body = _call_over_the_wire(name, arguments)
    return is_error, (yaml.safe_load(body) if body.strip() else {})


#: The two verbs, and the key each one reports its written half under.
WRITTEN_KEY = {"pm_update_many": "updated", "pm_archive_many": "archived"}


def _bulk_args(verb: str, ids: list[str]) -> dict:
    """A minimal well-formed call to ``verb`` over ``ids``."""
    args = {"ids": ",".join(ids)}
    if verb == "pm_update_many":
        args["status"] = "done"
    return args


# ─── the story's scenario, literally ─────────────────────────────


class TestFiftyItemsThreeFail:
    """50 items, 3 failing at the first, a middle and the last position."""

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_the_47_successes_are_reported_in_input_order(self, tmp_project, fifty, verb):
        ids, real, _ = fifty

        is_error, data = _sweep(verb, _bulk_args(verb, ids))

        assert is_error is False, data
        assert data["count"] == REAL_ITEMS
        assert [e["id"] for e in data[WRITTEN_KEY[verb]]] == real
        assert data["succeeded"] == real

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_the_3_failures_are_listed_with_reasons(self, tmp_project, fifty, verb):
        ids, _, missing = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert data["failed_count"] == BAD_ITEMS
        assert [f["id"] for f in data["failed"]] == missing, "input order, not sorted"
        for failure, item_id in zip(data["failed"], missing):
            # A reason, and one that names the item — never a bare empty string.
            assert failure["error"].strip()
            assert item_id in failure["error"]

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_nothing_is_hidden_the_two_halves_account_for_all_50(
        self, tmp_project, fifty, verb
    ):
        ids, _, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        reported = data["succeeded"] + [f["id"] for f in data["failed"]]
        assert sorted(reported) == sorted(ids)
        assert data["count"] + data["failed_count"] == 50

    def test_update_persists_all_47_writes(self, tmp_project, fifty):
        ids, real, missing = fifty

        _sweep("pm_update_many", _bulk_args("pm_update_many", ids))

        assert set(_statuses(tmp_project, real).values()) == {"done"}
        for gone in missing:
            with pytest.raises(Exception):
                _fresh_store(tmp_project).get(gone)

    def test_archive_persists_all_47_writes(self, tmp_project, fifty):
        ids, real, missing = fifty

        _sweep("pm_archive_many", _bulk_args("pm_archive_many", ids))

        assert all(_archived_flags(tmp_project, real).values())
        for gone in missing:
            with pytest.raises(Exception):
                _fresh_store(tmp_project).get(gone)

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_a_failure_at_the_first_position_does_not_stop_the_sweep(
        self, tmp_project, fifty, verb
    ):
        """The bad ID is item 1 of 50; items 2..50 still land."""
        ids, real, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert real[0] in data["succeeded"]
        assert data["count"] == REAL_ITEMS

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_a_failure_in_the_middle_does_not_roll_back_what_preceded_it(
        self, tmp_project, fifty, verb
    ):
        """The 24 items written before the middle failure stay written."""
        ids, real, _ = fifty
        before_the_middle_failure = real[:24]

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert data["succeeded"][:24] == before_the_middle_failure
        if verb == "pm_update_many":
            assert set(_statuses(tmp_project, before_the_middle_failure).values()) == {
                "done"
            }
        else:
            assert all(_archived_flags(tmp_project, before_the_middle_failure).values())

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_a_failure_at_the_last_position_does_not_undo_the_49_before_it(
        self, tmp_project, fifty, verb
    ):
        ids, real, missing = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert data["failed"][-1]["id"] == missing[-1]
        assert data["succeeded"][-1] == real[-1]

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_the_50_item_partial_failure_is_not_a_failed_call(
        self, tmp_project, fifty, verb
    ):
        """`is_error` stays unset and the body is a result, not an `error:`."""
        ids, _, _ = fifty

        is_error, body = _call_over_the_wire(verb, _bulk_args(verb, ids))

        assert is_error is False
        assert not body.lstrip().startswith("error:")
        assert yaml.safe_load(body)["partial"] is True


# ─── the shape, held identical across both verbs ─────────────────


class TestResultKeysAndTypes:
    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_a_partial_failure_carries_exactly_the_contract_keys(
        self, tmp_project, fifty, verb
    ):
        ids, _, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert set(data) == {
            WRITTEN_KEY[verb],
            "count",
            "failed",
            "failed_count",
            "succeeded",
            "partial",
        }

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_every_key_has_the_documented_type(self, tmp_project, fifty, verb):
        ids, _, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert isinstance(data[WRITTEN_KEY[verb]], list)
        assert isinstance(data["count"], int)
        assert isinstance(data["failed"], list)
        assert isinstance(data["failed_count"], int)
        assert isinstance(data["succeeded"], list)
        assert data["partial"] is True
        assert all(isinstance(i, str) for i in data["succeeded"])
        for failure in data["failed"]:
            assert set(failure) == {"id", "error"}
            assert isinstance(failure["id"], str)
            assert isinstance(failure["error"], str)

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_count_is_the_length_of_the_written_list(self, tmp_project, fifty, verb):
        ids, _, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert data["count"] == len(data[WRITTEN_KEY[verb]])
        assert data["failed_count"] == len(data["failed"])

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_the_failure_keys_are_absent_from_a_clean_sweep(
        self, tmp_project, fifty, verb
    ):
        """Their absence is the statement that everything landed."""
        _, real, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, real))

        assert set(data) == {WRITTEN_KEY[verb], "count"}
        for key in ("failed", "failed_count", "succeeded", "partial"):
            assert key not in data

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_partial_is_never_reported_false(self, tmp_project, fifty, verb):
        """`partial` is present-and-true or absent — a caller tests membership."""
        _, real, _ = fifty

        _, clean = _sweep(verb, _bulk_args(verb, real))

        assert clean.get("partial") is None

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_an_all_failed_sweep_is_still_a_partial_failure(self, tmp_project, verb):
        """Nothing landed, but the call itself worked and says so per item."""
        bad = ["US-TST-1-901", "US-TST-1-902", "US-TST-1-903"]

        is_error, data = _sweep(verb, _bulk_args(verb, bad))

        assert is_error is False, data
        assert data["count"] == 0
        assert data[WRITTEN_KEY[verb]] == []
        assert data["succeeded"] == []
        assert data["failed_count"] == 3
        assert data["partial"] is True

    def test_both_verbs_build_the_shape_from_one_code_path(self):
        """The guarantee behind every assertion above: there is only one builder."""
        import inspect

        from projectman import server

        source = inspect.getsource(server)
        # The keys are written in exactly one place.
        assert source.count('result["partial"] = True') == 1
        assert source.count('result["failed_count"]') == 1
        for verb in ("pm_update_many", "pm_archive_many"):
            body = inspect.getsource(getattr(server, verb))
            assert "_bulk_result(" in body
            assert "_bulk_failure(" in body


# ─── call-level rejection vs item-level failure ──────────────────


class TestTheRejectionBoundary:
    @pytest.mark.parametrize(
        "verb,arguments",
        [
            ("pm_update_many", {}),
            ("pm_update_many", {"ids": "US-TST-1-1"}),
            ("pm_update_many", {"updates": [{"status": "done"}]}),
            ("pm_update_many", {"updates": [{"id": "US-TST-1-1", "nope": 1}]}),
            ("pm_archive_many", {}),
            ("pm_archive_many", {"ids": "US-TST-1-1,US-TST-1-1"}),
        ],
    )
    def test_a_malformed_call_sets_is_error_and_writes_nothing(
        self, tmp_project, fifty, verb, arguments
    ):
        _, real, _ = fifty
        before = _statuses(tmp_project, real)

        is_error, body = _call_over_the_wire(verb, arguments)

        assert is_error is True
        assert not body.lstrip().startswith("error:")
        assert _statuses(tmp_project, real) == before
        assert not any(_archived_flags(tmp_project, real).values())

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_over_the_limit_is_rejected_whole_never_partially_written(
        self, tmp_project, fifty, verb
    ):
        from projectman.server import BULK_UPDATE_LIMIT

        _, real, _ = fifty
        too_many = [f"US-TST-1-{i}" for i in range(1, BULK_UPDATE_LIMIT + 2)]
        before = _statuses(tmp_project, real)

        is_error, _ = _call_over_the_wire(verb, _bulk_args(verb, too_many))

        assert is_error is True
        assert _statuses(tmp_project, real) == before

    def test_a_bad_value_on_one_item_is_soft_not_a_rejected_call(
        self, tmp_project, fifty
    ):
        """An invalid *value* belongs to its item; only a malformed call is hard."""
        _, real, _ = fifty

        is_error, data = _sweep(
            "pm_update_many",
            {
                "updates": [
                    {"id": real[0], "status": "nonsense"},
                    {"id": real[1], "status": "done"},
                ]
            },
        )

        assert is_error is False, data
        assert data["succeeded"] == [real[1]]
        assert data["failed"][0]["id"] == real[0]
        assert "nonsense" in data["failed"][0]["error"]
        assert _statuses(tmp_project, [real[0], real[1]]) == {
            real[0]: "todo",
            real[1]: "done",
        }

    def test_the_duplicate_rule_is_archives_alone_and_deliberate(
        self, tmp_project, fifty
    ):
        """Repeating an idempotent patch is harmless; archiving twice is not."""
        from projectman.server import pm_archive_many, pm_update_many

        _, real, _ = fifty

        with pytest.raises(ToolError, match="duplicate"):
            pm_archive_many(ids=f"{real[0]},{real[0]}")

        data = yaml.safe_load(pm_update_many(ids=f"{real[0]},{real[0]}", status="done"))
        assert "partial" not in data
        assert data["count"] == 2


# ─── the retry the contract tells callers to perform ─────────────


class TestRetryWithTheFailedIdsOnly:
    def test_update_retry_of_the_failed_ids_completes_the_work(self, tmp_project, fifty):
        from projectman.server import pm_create_tasks

        ids, real, missing = fifty
        _, first = _sweep("pm_update_many", _bulk_args("pm_update_many", ids))

        # Whatever made the three fail is fixed...
        pm_create_tasks(
            "US-TST-1",
            [
                {"title": f"Late {i}", "description": READY_BODY, "points": 1}
                for i in range(BAD_ITEMS)
            ],
        )
        retry_ids = [f["id"] for f in first["failed"]]
        assert retry_ids == missing

        is_error, second = _sweep(
            "pm_update_many", _bulk_args("pm_update_many", retry_ids)
        )

        assert is_error is False, second
        assert "partial" not in second
        assert second["count"] == BAD_ITEMS
        # The first call's successes were never re-sent and never disturbed.
        assert set(_statuses(tmp_project, real + missing).values()) == {"done"}

    def test_archive_retry_of_the_failed_ids_completes_the_work(
        self, tmp_project, fifty
    ):
        from projectman.server import pm_create_tasks

        ids, real, missing = fifty
        _, first = _sweep("pm_archive_many", _bulk_args("pm_archive_many", ids))

        pm_create_tasks(
            "US-TST-1",
            [
                {"title": f"Late {i}", "description": READY_BODY, "points": 1}
                for i in range(BAD_ITEMS)
            ],
        )
        retry_ids = [f["id"] for f in first["failed"]]

        is_error, second = _sweep(
            "pm_archive_many", _bulk_args("pm_archive_many", retry_ids)
        )

        assert is_error is False, second
        assert "partial" not in second
        assert second["count"] == BAD_ITEMS
        assert all(_archived_flags(tmp_project, real + missing).values())

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_the_failed_ids_are_reusable_verbatim(self, tmp_project, fifty, verb):
        """`failed[].id` is the ID as the caller wrote it, ready to re-send."""
        ids, _, _ = fifty

        _, data = _sweep(verb, _bulk_args(verb, ids))

        assert all(f["id"] in ids for f in data["failed"])

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_the_retry_touches_only_the_failed_ids(self, tmp_project, fifty, verb):
        """The retry rewrites the 3 named items and *nothing else*.

        The sibling retry tests show the first call's successes still read
        `done`/archived afterwards — but they read that way already, so a
        retry that silently rewrote all 50 would pass them too.  Compare the
        47 item files byte for byte instead: a re-write would move `updated:`
        or reorder the file even when the visible state is unchanged.
        """
        from projectman.server import pm_create_tasks

        ids, real, missing = fifty
        _, first = _sweep(verb, _bulk_args(verb, ids))
        before = _item_files(tmp_project, real)
        assert len(before) == REAL_ITEMS

        # Fix what made the three fail, then re-issue with exactly `failed`.
        pm_create_tasks(
            "US-TST-1",
            [
                {"title": f"Late {i}", "description": READY_BODY, "points": 1}
                for i in range(BAD_ITEMS)
            ],
        )
        retry_ids = [f["id"] for f in first["failed"]]
        assert retry_ids == missing

        is_error, second = _sweep(verb, _bulk_args(verb, retry_ids))

        assert is_error is False, second
        assert [e["id"] for e in second[WRITTEN_KEY[verb]]] == missing
        assert _item_files(tmp_project, real) == before, (
            "the retry rewrote items it was not given"
        )


# ─── the contract is written down, once, in both places ──────────


class TestTheContractIsDocumented:
    def _docs(self) -> str:
        return (
            Path(__file__).resolve().parents[1] / "docs/reference/mcp-tools.md"
        ).read_text()

    def test_the_reference_has_one_shared_partial_failure_section(self):
        docs = self._docs()

        assert "\n## Partial failure\n" in docs
        assert docs.count("\n## Partial failure\n") == 1

    def test_both_verbs_link_to_that_one_section(self):
        docs = self._docs()

        for verb in ("pm_update_many", "pm_archive_many"):
            entry = docs.split(f"### {verb}(", 1)[1].split("\n### ", 1)[0]
            assert "[Partial failure](#partial-failure)" in entry, verb

    def test_the_section_states_every_clause_of_the_contract(self):
        docs = self._docs().split("\n## Partial failure\n", 1)[1].split("\n## ", 1)[0]

        assert "Fail-soft per item" in docs
        assert "No rollback" in docs
        assert "Call-level rejection" in docs
        assert "`failed_count`" in docs and "`succeeded`" in docs
        assert "only when ≥ 1 item failed" in docs
        assert "`is_error` is never set" in docs
        assert "re-issue the same call with `ids` set to the `failed` IDs only" in docs

    @pytest.mark.parametrize("verb", sorted(WRITTEN_KEY))
    def test_each_docstring_states_the_contract_too(self, verb):
        from projectman import server

        doc = getattr(server, verb).__doc__

        assert "Fail-soft per item" in doc
        assert "No rollback" in doc
        assert "Call-level rejection" in doc
        assert "`is_error` is never set for a partial failure" in doc
        assert "Retry" in doc and "`failed` IDs" in doc
        assert "in input order" in doc

    def test_the_shared_builder_carries_the_contract_in_prose(self):
        from projectman.server import _bulk_result

        doc = _bulk_result.__doc__

        assert "pm_update_many" in doc and "pm_archive_many" in doc
        assert "docs/reference/mcp-tools.md" in doc
