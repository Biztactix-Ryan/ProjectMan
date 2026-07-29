"""The truncation boundary and the flag contract, at the tool layer.

US-PM-1-5 — acceptance criteria 2 and 4 of US-PM-1:

2. "Response carries a note_truncated flag so the caller knows"
4. "Regression test covers a note at the limit and well over it"

``tests/test_run_log_truncation.py`` pins the pure helper, and
``tests/test_note_truncated_flag.py`` pins the *existence* of the flag and its
staleness guards.  This module pins the two things that decide whether the flag
is actually usable by a machine:

* the **boundary**, as a triple — ``limit - 1``, exactly ``limit``, ``limit + 1``
  — driven through ``pm_update``, not through the helper.  ``>`` vs ``>=`` in the
  comparison is a one-character mistake that only the exact-limit case catches;
* the **arithmetic**, across sizes that straddle powers of ten.  The marker
  ``...[truncated N chars]`` is itself part of the stored note, so the digit
  count of ``N`` changes how much room is left, which changes ``N``.  That fixed
  point is solved by iteration in ``truncate_run_log_note``; every extra digit
  is a fresh chance for an off-by-one, so 4097 / 5000 / 10000 / 100000 /
  1000000 are all exercised and the reported numbers reconciled against the
  note that actually reached disk.

Two traps get their own coverage:

* the limit is in **characters, not bytes**.  A 4096-character CJK or emoji note
  is three to four times the limit in UTF-8 bytes and must still be stored
  whole.  Every assertion here also checks the note is over the limit in bytes,
  so a byte-length regression cannot pass;
* **absence means false.**  The five fields are emitted only on the truncated
  path, so a caller reads "no ``note_truncated`` key" as "stored whole".  That
  makes partial emission — some fields but not others — a protocol violation,
  not a cosmetic one, and it is asserted as all-or-nothing here.  See
  ``_note_truncation_fields`` in server.py for why the fields are omitted rather
  than emitted as false (response bytes are a tracked cost for this epic).

NOTE (port forward): ``pm_done_next`` does not exist in this checkout.  It is
the higher-traffic note-bearing entry point upstream; mirror this module
against it when these changes are ported onto a newer main.
"""

import json
import re

import pytest
import yaml

from projectman.store import RUN_LOG_NOTE_LIMIT

MARKER_RE = re.compile(r"\.\.\.\[truncated (\d+) chars\]$")

TRUNCATION_KEYS = {
    "note_truncated",
    "note_original_length",
    "note_stored_length",
    "note_dropped_chars",
    "note_limit",
}

# Sizes that straddle powers of ten, so the marker's digit count — which feeds
# back into the dropped count — takes every width from 2 to 6 digits.
OVER_LIMIT_SIZES = [
    RUN_LOG_NOTE_LIMIT + 1,  # 4097, smallest truncating note
    5_000,
    10_000,
    100_000,
    1_000_000,
]


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    """Run the real MCP tools against a throwaway project with a cold cache."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import _cache

    _store_cache.clear()
    _cache.clear()
    yield
    _store_cache.clear()
    _cache.clear()


@pytest.fixture
def task():
    """A story with one task, ready to be updated."""
    from projectman.server import pm_create_story, pm_create_task

    pm_create_story("Story", "Body")
    pm_create_task("US-TST-1", "Task one", "Do it")
    return "US-TST-1-1"


def update(item_id: str, **kwargs) -> dict:
    """Call ``pm_update`` and parse the real response as YAML.

    Deliberately parses rather than substring-matching: the flag has to survive
    the actual serialization the caller receives, with its types intact.
    """
    from projectman.server import pm_update

    raw = pm_update(item_id, **kwargs)
    assert isinstance(raw, str)
    assert not raw.startswith("error:"), raw
    payload = yaml.safe_load(raw)
    assert isinstance(payload, dict), raw
    assert "updated" in payload, raw
    return payload


def stored_note(item_id: str) -> str:
    """The note that actually reached the run log, newest entry first."""
    from projectman.server import pm_run_log

    raw = pm_run_log(item_id)
    assert not raw.startswith("error:"), raw
    entries = json.loads(raw)
    assert entries, "no run-log entry was written"
    return entries[0]["note"]


def assert_reports_nothing(payload: dict) -> None:
    """The response must carry no truncation fields at all."""
    assert TRUNCATION_KEYS.isdisjoint(payload), sorted(
        TRUNCATION_KEYS & set(payload)
    )


class TestBoundaryTriple:
    """limit-1, limit, limit+1 driven through ``pm_update``.

    At and below the cap the fields must be *absent* — that is how this design
    says "false".  The first truncating length is limit+1 and no other.
    """

    @pytest.mark.parametrize(
        "size",
        [1, RUN_LOG_NOTE_LIMIT - 2, RUN_LOG_NOTE_LIMIT - 1, RUN_LOG_NOTE_LIMIT],
        ids=["one-char", "limit-2", "limit-1", "exactly-limit"],
    )
    def test_at_or_below_the_limit_reports_nothing(self, task, size):
        assert_reports_nothing(update(task, outcome="success", note="x" * size))

    @pytest.mark.parametrize(
        "size",
        [1, RUN_LOG_NOTE_LIMIT - 1, RUN_LOG_NOTE_LIMIT],
        ids=["one-char", "limit-1", "exactly-limit"],
    )
    def test_at_or_below_the_limit_is_stored_byte_for_byte(self, task, size):
        note = "x" * size
        update(task, outcome="success", note=note)
        assert stored_note(task) == note

    def test_one_over_the_limit_reports_every_field(self, task):
        payload = update(
            task, outcome="success", note="x" * (RUN_LOG_NOTE_LIMIT + 1)
        )
        assert TRUNCATION_KEYS <= set(payload), sorted(
            TRUNCATION_KEYS - set(payload)
        )
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == RUN_LOG_NOTE_LIMIT + 1

    def test_one_over_the_limit_is_actually_shortened(self, task):
        note = "x" * (RUN_LOG_NOTE_LIMIT + 1)
        update(task, outcome="success", note=note)
        stored = stored_note(task)
        assert len(stored) <= RUN_LOG_NOTE_LIMIT
        assert stored != note
        assert MARKER_RE.search(stored), stored[-60:]

    def test_the_flag_flips_exactly_once_across_the_boundary(self, task):
        """Walk limit-1 -> limit -> limit+1 and pin the transition point."""
        flags = [
            "note_truncated" in update(task, outcome="success", note="x" * size)
            for size in (
                RUN_LOG_NOTE_LIMIT - 1,
                RUN_LOG_NOTE_LIMIT,
                RUN_LOG_NOTE_LIMIT + 1,
            )
        ]
        assert flags == [False, False, True]


class TestFlagArithmetic:
    """Every reported number must reconcile with the note that reached disk."""

    @pytest.fixture(params=OVER_LIMIT_SIZES, ids=lambda s: f"{s}-chars")
    def truncated(self, request, task):
        note = "q" * request.param
        payload = update(task, status="done", outcome="success", note=note)
        return note, payload, stored_note(task)

    def test_flag_is_true(self, truncated):
        _, payload, _ = truncated
        assert payload["note_truncated"] is True

    def test_original_length_is_what_the_caller_sent(self, truncated):
        note, payload, _ = truncated
        assert payload["note_original_length"] == len(note)

    def test_stored_length_matches_the_note_on_disk(self, truncated):
        _, payload, stored = truncated
        assert payload["note_stored_length"] == len(stored)

    def test_stored_length_never_exceeds_the_limit(self, truncated):
        _, payload, _ = truncated
        assert payload["note_stored_length"] <= RUN_LOG_NOTE_LIMIT

    def test_stored_length_uses_all_the_room_available(self, truncated):
        """A truncating note fills the cap exactly — marker included.

        Under-filling would mean the fixed-point loop settled a digit short.
        """
        _, payload, _ = truncated
        assert payload["note_stored_length"] == RUN_LOG_NOTE_LIMIT

    def test_dropped_chars_equals_original_minus_kept(self, truncated):
        """kept + dropped == original, where kept excludes the marker."""
        note, payload, stored = truncated
        match = MARKER_RE.search(stored)
        assert match, stored[-60:]
        kept = stored[: -len(match.group(0))]
        assert len(kept) + payload["note_dropped_chars"] == len(note)
        assert payload["note_dropped_chars"] == len(note) - (
            payload["note_stored_length"] - len(match.group(0))
        )

    def test_marker_states_the_same_count_it_reports(self, truncated):
        _, payload, stored = truncated
        match = MARKER_RE.search(stored)
        assert match, stored[-60:]
        assert int(match.group(1)) == payload["note_dropped_chars"]

    def test_kept_prefix_is_the_head_of_the_original(self, truncated):
        note, _, stored = truncated
        match = MARKER_RE.search(stored)
        kept = stored[: -len(match.group(0))]
        assert kept == note[: len(kept)]

    def test_limit_is_reported_verbatim(self, truncated):
        _, payload, _ = truncated
        assert payload["note_limit"] == RUN_LOG_NOTE_LIMIT

    def test_status_write_still_landed(self, truncated):
        _, payload, _ = truncated
        assert payload["updated"]["status"] == "done"

    def test_marker_width_grows_with_the_dropped_count(self, task):
        """The marker is inside the budget, so its digit count must adapt.

        If the marker length were computed once from a first guess instead of
        solved as a fixed point, the count it prints and the room it reserves
        would disagree at exactly these crossings.
        """
        widths = []
        for size in OVER_LIMIT_SIZES:
            payload = update(task, outcome="success", note="q" * size)
            match = MARKER_RE.search(stored_note(task))
            assert match
            widths.append(len(match.group(0)))
            # Room reserved == room actually used, at every width.
            assert payload["note_dropped_chars"] == int(match.group(1))
            assert payload["note_stored_length"] == RUN_LOG_NOTE_LIMIT
        assert widths == sorted(widths)
        assert len(set(widths)) > 1, widths


class TestAbsenceMeansFalse:
    """The contract that lets a caller read "no key" as "not truncated"."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"outcome": "success", "note": "short"},
            {"outcome": "success", "note": "x" * RUN_LOG_NOTE_LIMIT},
            {"outcome": "success", "note": "x" * (RUN_LOG_NOTE_LIMIT + 1)},
            {"status": "review"},
            {"points": 3},
            {"status": "done", "outcome": "success", "note": "y" * 90_000},
        ],
        ids=["short", "at-limit", "over-limit", "status-only", "field-only", "huge"],
    )
    def test_fields_are_all_present_or_all_absent(self, task, kwargs):
        """Partial emission would make absence ambiguous, so forbid it."""
        present = TRUNCATION_KEYS & set(update(task, **kwargs))
        assert present in (set(), TRUNCATION_KEYS), sorted(present)

    @pytest.mark.parametrize(
        "size", [0, 1, RUN_LOG_NOTE_LIMIT - 1, RUN_LOG_NOTE_LIMIT]
    )
    def test_the_flag_is_never_emitted_as_false(self, task, size):
        """"False" is spelled as absence; an explicit false would be a change."""
        payload = update(task, outcome="success", note="x" * size)
        assert "note_truncated" not in payload

    def test_a_fitting_note_adds_no_keys_beyond_updated(self, task):
        payload = update(task, status="done", outcome="success", note="fits fine")
        assert set(payload) == {"updated"}

    def test_a_truncated_note_adds_exactly_the_five_keys(self, task):
        payload = update(
            task, status="done", outcome="success", note="x" * 9_000
        )
        assert set(payload) == {"updated"} | TRUNCATION_KEYS


class TestSerializationPath:
    """The flag has to survive the real response the caller parses."""

    @pytest.fixture
    def payload(self, task):
        return update(
            task, status="done", outcome="success", note="w" * (RUN_LOG_NOTE_LIMIT * 3)
        )

    def test_flag_is_a_real_boolean(self, payload):
        assert isinstance(payload["note_truncated"], bool)
        assert payload["note_truncated"] is not None

    @pytest.mark.parametrize(
        "key",
        [
            "note_original_length",
            "note_stored_length",
            "note_dropped_chars",
            "note_limit",
        ],
    )
    def test_lengths_are_real_integers(self, payload, key):
        value = payload[key]
        assert isinstance(value, int) and not isinstance(value, bool), repr(value)

    def test_fields_are_top_level_siblings_of_updated(self, payload):
        assert isinstance(payload["updated"], dict)
        assert "note_truncated" not in payload["updated"]

    def test_response_round_trips_through_yaml_unchanged(self, payload):
        assert yaml.safe_load(yaml.safe_dump(payload)) == payload


class TestMultiByteBoundary:
    """The cap counts characters.  Bytes are not characters.

    A 4096-character CJK note is 12288 UTF-8 bytes; an emoji note is 16384.  If
    the cap were ever measured in bytes these would truncate, so each case also
    asserts the note is over the limit in bytes — that is what makes the test
    bite a byte-length regression rather than merely pass.
    """

    CHARS = {
        "latin1-supplement": "é",  # 2 bytes
        "cjk": "日",  # 3 bytes
        "astral-emoji": "\U0001f600",  # 4 bytes, still len() == 1
        "cyrillic": "Ж",  # 2 bytes
    }

    @pytest.mark.parametrize("char", CHARS.values(), ids=list(CHARS))
    def test_multibyte_note_at_the_limit_is_not_truncated(self, task, char):
        note = char * RUN_LOG_NOTE_LIMIT
        assert len(note) == RUN_LOG_NOTE_LIMIT
        assert len(note.encode("utf-8")) > RUN_LOG_NOTE_LIMIT, "not a real test"

        assert_reports_nothing(update(task, outcome="success", note=note))

    @pytest.mark.parametrize("char", CHARS.values(), ids=list(CHARS))
    def test_multibyte_note_at_the_limit_survives_the_round_trip(self, task, char):
        note = char * RUN_LOG_NOTE_LIMIT
        update(task, outcome="success", note=note)
        stored = stored_note(task)
        assert stored == note
        assert len(stored) == RUN_LOG_NOTE_LIMIT

    @pytest.mark.parametrize("char", CHARS.values(), ids=list(CHARS))
    def test_multibyte_note_one_over_the_limit_does_truncate(self, task, char):
        note = char * (RUN_LOG_NOTE_LIMIT + 1)
        payload = update(task, outcome="success", note=note)
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == RUN_LOG_NOTE_LIMIT + 1

    def test_multibyte_truncation_arithmetic_is_in_characters(self, task):
        note = "日" * 10_000
        payload = update(task, outcome="success", note=note)
        stored = stored_note(task)
        match = MARKER_RE.search(stored)
        assert match, stored[-60:]
        kept = stored[: -len(match.group(0))]
        assert payload["note_original_length"] == 10_000
        assert len(kept) + payload["note_dropped_chars"] == 10_000
        assert payload["note_stored_length"] == len(stored) <= RUN_LOG_NOTE_LIMIT

    def test_a_truncated_multibyte_note_is_not_cut_mid_character(self, task):
        """Slicing a ``str`` cannot split a code point — pin it anyway.

        A future byte-oriented implementation would produce mojibake here, and
        the failure would be silent in the length arithmetic alone.
        """
        note = "\U0001f600" * 20_000
        update(task, outcome="success", note=note)
        stored = stored_note(task)
        match = MARKER_RE.search(stored)
        kept = stored[: -len(match.group(0))]
        assert "�" not in stored
        assert set(kept) == {"\U0001f600"}
        assert kept.encode("utf-8").decode("utf-8") == kept


class TestDegenerateNotes:
    """Empty, blank, missing and marker-shaped notes must all behave."""

    def test_empty_note_reports_nothing(self, task):
        assert_reports_nothing(update(task, outcome="success", note=""))

    def test_empty_note_still_writes_a_run_log_entry(self, task):
        update(task, outcome="success", note="")
        assert stored_note(task) == ""

    def test_whitespace_only_note_reports_nothing(self, task):
        assert_reports_nothing(update(task, outcome="success", note="   \n\t  "))

    def test_whitespace_only_note_is_stored_verbatim(self, task):
        update(task, outcome="success", note="   \n\t  ")
        assert stored_note(task) == "   \n\t  "

    def test_outcome_without_a_note_reports_nothing(self, task):
        assert_reports_nothing(update(task, status="done", outcome="success"))

    def test_outcome_without_a_note_still_logs(self, task):
        update(task, status="done", outcome="success")
        assert stored_note(task) == ""

    def test_a_note_that_is_only_the_marker_is_left_alone(self, task):
        """A short note that *looks* truncated must not be reported as such."""
        note = "...[truncated 5 chars]"
        payload = update(task, outcome="success", note=note)
        assert_reports_nothing(payload)
        assert stored_note(task) == note

    def test_an_oversized_note_ending_in_a_marker_reports_the_real_count(self, task):
        """The caller's own marker text must not be mistaken for ours."""
        note = "z" * 8_000 + "...[truncated 1 chars]"
        payload = update(task, outcome="success", note=note)
        assert payload["note_truncated"] is True
        assert payload["note_original_length"] == len(note)
        match = MARKER_RE.search(stored_note(task))
        assert int(match.group(1)) == payload["note_dropped_chars"]
        assert payload["note_dropped_chars"] > 1
