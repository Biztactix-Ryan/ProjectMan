"""Tests for usage-telemetry failure classification (US-PM-6-7).

Covers story AC 2: hard errors, soft errors and malformed inputs are reported
separately, plus a combined true failure rate that counts distinct calls.

The strings used here are the real ones observed in the corpora described in
`the original usage studies` -- the 1024-char run-log rejection, the ``task is not ready to grab``
envelope, ``<tool_use_error>InputValidationError: ...``, and the ``pm_get``
success payload that merely *contains* an ``error:`` field and must not be
counted.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import tools.usage_telemetry as tx_pkg
from tools.usage_telemetry import classify as cf
from tools.usage_telemetry.extract import Extraction, ToolCall, ToolResult, scan

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- fixtures --

#: The single most-hit soft error in every study corpus.
SOFT_NOTE_LIMIT = '{"result":"error: Run-log note must be 1024 characters or fewer"}'
SOFT_NOT_READY = (
    '{"result":"error: task is not ready to grab\\nblockers:\\n'
    "- status is 'review', not 'todo'\"}"
)
SOFT_NO_CONFIG = '{"result":"error: No .project/config.yaml found in any parent directory"}'
HARD_UNPARSABLE = (
    "<tool_use_error>InputValidationError: mcp__projectman__pm_update was called "
    "with input that could not be parsed as JSON.\nYou sent (first 53 of 53 bytes)"
    "</tool_use_error>"
)
HARD_VALIDATION = (
    "Error executing tool pm_grab: 1 validation error for pm_grabArguments\n"
    "task_id\n  Field required [type=missing, input_value={'id': 'US-TOM-43-9'}]"
)
#: A *successful* pm_get listing that contains ``error:`` inside the payload.
SUCCESS_WITH_ERROR_FIELD = (
    '{"result":"- id: US-SK-8-1\\n  error: \'Task not found: US-SK-8-1\'\\n'
    "- id: US-SK-8-2\\n  error: 'Task not found: US-SK-8-2'\"}"
)
SUCCESS_PLAIN = '{"result":"ok"}'


def make_call(
    tool="pm_update",
    text=SUCCESS_PLAIN,
    is_error=False,
    tool_input=None,
    with_result=True,
    tool_use_id="tu-1",
):
    call = ToolCall(
        tool_use_id=tool_use_id,
        name=f"mcp__projectman__{tool}",
        input={} if tool_input is None else tool_input,
        timestamp="2026-07-29T00:00:00Z",
        session="sess-a",
        session_id="sess-a",
        project="proj",
        source_file="proj/sess-a.jsonl",
        line_no=1,
        seq=0,
    )
    if with_result:
        call.result = ToolResult(tool_use_id=tool_use_id, is_error=is_error, text=text)
    return call


def _record(content):
    return {
        "type": "assistant",
        "sessionId": "sess-a",
        "timestamp": "2026-07-29T00:00:00Z",
        "message": {"content": content},
    }


@pytest.fixture
def corpus(tmp_path):
    """Transcript corpus with one call of each class, joinable 100%."""
    cases = [
        ("pm_update", {"id": "A"}, SUCCESS_PLAIN, False),
        ("pm_get", {"id": "B"}, SUCCESS_WITH_ERROR_FIELD, False),
        ("pm_update", {"id": "C", "note": "x"}, SOFT_NOTE_LIMIT, False),
        ("pm_grab", {"task_id": "D"}, SOFT_NOT_READY, False),
        ("pm_grab", {"id": "E"}, HARD_VALIDATION, True),
        ("pm_update", {"__unparsedToolInput": '{"id": "F", "assignee": }'},
         HARD_UNPARSABLE, True),
    ]
    records = []
    for i, (tool, tool_input, text, is_error) in enumerate(cases):
        tid = f"tu-{i}"
        records.append(
            _record([
                {
                    "type": "tool_use",
                    "id": tid,
                    "name": f"mcp__projectman__{tool}",
                    "input": tool_input,
                }
            ])
        )
        records.append(
            _record([
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": text,
                    "is_error": is_error,
                }
            ])
        )
    path = tmp_path / "proj" / "sess-a.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return tmp_path


# ------------------------------------------------------- single-call class --


def test_hard_error_detected_via_is_error():
    call = make_call(text=HARD_VALIDATION, is_error=True)
    assert cf.is_hard_error(call)
    assert classify_primary(call) == cf.HARD_ERROR


def classify_primary(call):
    return cf.classify(call).primary


def test_soft_error_detected_when_is_error_is_false():
    """The whole point: a 200-OK body that is an error envelope."""
    call = make_call(text=SOFT_NOTE_LIMIT, is_error=False)
    assert not cf.is_hard_error(call)
    assert cf.is_soft_error(call)
    assert classify_primary(call) == cf.SOFT_ERROR


@pytest.mark.parametrize("text", [SOFT_NOTE_LIMIT, SOFT_NOT_READY, SOFT_NO_CONFIG])
def test_real_soft_error_bodies_all_match(text):
    assert cf.is_soft_error(make_call(text=text))


def test_soft_error_envelope_pattern_named():
    assert cf.soft_error_pattern(SOFT_NOTE_LIMIT) == "envelope"


def test_soft_error_bare_prefix_variant():
    """The harness's own overflow error is not the envelope but is a failure."""
    text = "Error: result (74,006 characters) exceeds maximum allowed tokens."
    assert cf.soft_error_pattern(text) == "bare"
    assert cf.is_soft_error(make_call(tool="pm_batch_get", text=text))


def test_successful_payload_containing_error_field_is_not_a_soft_error():
    """A loose ``error:\\s`` search over-counts; the pattern is anchored."""
    call = make_call(tool="pm_get", text=SUCCESS_WITH_ERROR_FIELD)
    assert not cf.is_soft_error(call)
    assert classify_primary(call) == cf.SUCCESS


def test_error_word_mid_body_is_not_a_soft_error():
    call = make_call(text='{"result":"# Audit\\n**Errors:** 0 | **Warnings:** 0"}')
    assert not cf.is_soft_error(call)
    assert classify_primary(call) == cf.SUCCESS


def test_malformed_input_detected_via_unparsed_key():
    call = make_call(tool_input={"__unparsedToolInput": '{"id": "X", "assignee": }'})
    assert cf.is_malformed_input(call)
    assert classify_primary(call) == cf.MALFORMED_INPUT


def test_malformed_key_name_is_the_documented_one():
    assert cf.MALFORMED_INPUT_KEY == "__unparsedToolInput"


def test_well_formed_input_is_not_malformed():
    assert not cf.is_malformed_input(make_call(tool_input={"id": "X"}))


def test_success_is_neither_class():
    item = cf.classify(make_call())
    assert not (item.hard or item.soft or item.malformed)
    assert not item.failed
    assert item.primary == cf.SUCCESS


def test_unmatched_call_is_not_a_failure():
    item = cf.classify(make_call(with_result=False))
    assert item.primary == cf.UNMATCHED
    assert not item.failed


def test_soft_error_message_is_extracted_and_first_line_only():
    assert (
        cf.soft_error_message(SOFT_NOTE_LIMIT)
        == "Run-log note must be 1024 characters or fewer"
    )
    assert cf.soft_error_message(SOFT_NOT_READY) == "task is not ready to grab"


def test_soft_error_message_is_none_for_successes():
    assert cf.soft_error_message(SUCCESS_PLAIN) is None
    assert cf.soft_error_message(None) is None


# ------------------------------------------------------------- precedence --


def test_malformed_and_hard_together_take_malformed_as_primary():
    """The 27 real overlaps: unparsable input also trips ``is_error``."""
    call = make_call(
        tool_input={"__unparsedToolInput": "{"}, text=HARD_UNPARSABLE, is_error=True
    )
    item = cf.classify(call)
    assert item.malformed and item.hard
    assert item.primary == cf.MALFORMED_INPUT
    assert item.classes == (cf.MALFORMED_INPUT, cf.HARD_ERROR)


def test_precedence_order_is_documented_and_applied():
    assert cf.PRECEDENCE == (cf.MALFORMED_INPUT, cf.HARD_ERROR, cf.SOFT_ERROR)


def test_hard_and_soft_together_take_hard_as_primary():
    call = make_call(text=SOFT_NOTE_LIMIT, is_error=True)
    item = cf.classify(call)
    assert item.hard and item.soft
    assert item.primary == cf.HARD_ERROR


def test_malformed_call_without_result_still_counts_as_malformed():
    item = cf.classify(make_call(tool_input={"__unparsedToolInput": "{"}, with_result=False))
    assert item.primary == cf.MALFORMED_INPUT
    assert item.failed


# ------------------------------------------------------------- aggregation --


@pytest.fixture
def report():
    calls = [
        make_call(tool_use_id="s1"),
        make_call(tool="pm_get", text=SUCCESS_WITH_ERROR_FIELD, tool_use_id="s2"),
        make_call(text=SOFT_NOTE_LIMIT, tool_use_id="f1"),
        make_call(text=SOFT_NOTE_LIMIT, tool_use_id="f2"),
        make_call(tool="pm_grab", text=SOFT_NOT_READY, tool_use_id="f3"),
        make_call(tool="pm_grab", text=HARD_VALIDATION, is_error=True, tool_use_id="f4"),
        make_call(
            tool_input={"__unparsedToolInput": "{"},
            text=HARD_UNPARSABLE,
            is_error=True,
            tool_use_id="f5",
        ),
    ]
    return cf.classify_all(calls)


def test_three_classes_reported_separately(report):
    assert report.soft == 3
    assert report.hard == 2  # inclusive: includes the malformed+hard overlap
    assert report.malformed == 1


def test_combined_rate_counts_distinct_calls_not_the_sum(report):
    assert report.hard + report.soft + report.malformed == 6
    assert report.failures == 5  # the malformed+hard call is counted once
    assert report.total == 7
    assert report.failure_rate == pytest.approx(5 / 7)


def test_exclusive_counts_partition_the_corpus(report):
    exclusive = report.primary_counts
    assert exclusive == {
        cf.MALFORMED_INPUT: 1,
        cf.HARD_ERROR: 1,
        cf.SOFT_ERROR: 3,
        cf.SUCCESS: 2,
        cf.UNMATCHED: 0,
    }
    assert sum(exclusive.values()) == report.total
    failing = sum(exclusive[c] for c in cf.PRECEDENCE)
    assert failing == report.failures


def test_overlaps_are_reported(report):
    assert report.overlaps == {"malformed_input+hard_error": 1}


def test_rates_use_total_calls_as_denominator(report):
    assert report.soft_rate == pytest.approx(3 / 7)
    assert report.hard_rate == pytest.approx(2 / 7)
    assert report.malformed_rate == pytest.approx(1 / 7)


def test_successes_exclude_every_failure_class(report):
    assert report.successes == 2
    assert report.successes + report.failures + report.unmatched == report.total


def test_empty_corpus_rates_are_zero_not_a_crash():
    empty = cf.classify_all([])
    assert empty.total == 0
    assert empty.failure_rate == 0.0
    assert empty.failures == 0


def test_soft_pattern_counts(report):
    assert report.soft_patterns["envelope"] == 3
    assert report.soft_patterns["bare"] == 0


def test_failing_filters_by_inclusive_class(report):
    assert len(report.failing()) == 5
    assert len(report.failing(cf.HARD_ERROR)) == 2
    assert len(report.failing(cf.SOFT_ERROR)) == 3
    assert len(report.failing(cf.MALFORMED_INPUT)) == 1
    with pytest.raises(ValueError):
        report.failing("nope")


def test_top_messages_groups_by_tool_and_message(report):
    top = report.top_messages()
    assert top[0] == ("pm_update", "Run-log note must be 1024 characters or fewer", 2)
    assert ("pm_grab", "task is not ready to grab", 1) in top


# ---------------------------------------------------------------- per tool --


def test_per_tool_breakdown_separates_the_classes(report):
    by_tool = report.by_tool()
    assert set(by_tool) == {"pm_update", "pm_grab", "pm_get"}

    update = by_tool["pm_update"]
    assert (update.calls, update.soft, update.hard, update.malformed) == (4, 2, 1, 1)
    assert update.failures == 3
    assert update.failure_rate == pytest.approx(3 / 4)
    assert update.successes == 1

    grab = by_tool["pm_grab"]
    assert (grab.calls, grab.soft, grab.hard, grab.malformed) == (2, 1, 1, 0)
    assert grab.failures == 2

    get = by_tool["pm_get"]
    assert (get.calls, get.failures) == (1, 0)


def test_per_tool_is_ordered_by_failures(report):
    assert list(report.by_tool()) == ["pm_update", "pm_grab", "pm_get"]


def test_per_tool_call_counts_sum_to_total(report):
    assert sum(r.calls for r in report.by_tool().values()) == report.total
    assert sum(r.failures for r in report.by_tool().values()) == report.failures


def test_tool_name_has_mcp_prefix_stripped(report):
    assert all(not t.startswith("mcp__") for t in report.by_tool())


# -------------------------------------------------------------- end to end --


def test_classify_over_a_scanned_corpus(corpus):
    extraction = scan(root=corpus)
    assert extraction.match_rate == 1.0
    report = cf.classify_all(extraction.calls)
    assert report.total == 6
    assert report.soft == 2
    assert report.hard == 2
    assert report.malformed == 1
    assert report.failures == 4
    assert report.successes == 2
    assert report.failure_rate == pytest.approx(4 / 6)


def test_as_dict_is_json_serialisable_and_complete(report):
    payload = report.as_dict()
    assert json.loads(json.dumps(payload))
    assert payload["inclusive"] == {
        "hard_error": 2,
        "soft_error": 3,
        "malformed_input": 1,
    }
    assert payload["failures"] == 5
    assert payload["rates"]["combined_failure_rate"] == pytest.approx(5 / 7)
    assert {row["tool"] for row in payload["by_tool"]} == {
        "pm_update",
        "pm_grab",
        "pm_get",
    }


def test_format_report_shows_all_three_classes_and_the_combined_rate(report):
    text = cf.format_report(report)
    assert "hard errors" in text
    assert "soft errors" in text
    assert "malformed inputs" in text
    assert "COMBINED" in text
    assert "per tool" in text


def test_cli_text_output(corpus):
    proc = subprocess.run(
        [sys.executable, "-m", "tools.usage_telemetry.classify", "--root", str(corpus)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "COMBINED" in proc.stdout
    assert "pm_update" in proc.stdout


def test_cli_json_output(corpus):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.usage_telemetry.classify",
            "--root",
            str(corpus),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["total_calls"] == 6
    assert payload["inclusive"]["soft_error"] == 2
    assert payload["failures"] == 4


def test_cli_reports_error_on_empty_corpus(tmp_path):
    (tmp_path / "empty").mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.usage_telemetry.classify",
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 2


def test_package_reexports_classification_api():
    for name in (
        "classify_all",
        "Classification",
        "CallClass",
        "MALFORMED_INPUT_KEY",
        "SOFT_ERROR_PATTERNS",
    ):
        assert name in tx_pkg.__all__
        assert hasattr(tx_pkg, name)


def test_package_rejects_unknown_attributes():
    with pytest.raises(AttributeError):
        tx_pkg.no_such_name


def test_package_attribute_classify_is_the_submodule_not_the_function():
    """Re-exporting ``classify()`` would shadow the submodule -- it must not."""
    assert tx_pkg.classify is cf
    assert "classify" not in tx_pkg.__all__
    assert callable(cf.classify)


def test_classification_does_not_mutate_the_extraction():
    """Classification is a read-only view -- US-PM-6-8/9 build on the same calls."""
    call = make_call(text=SOFT_NOTE_LIMIT)
    extraction = Extraction(calls=[call])
    before = call.to_record()
    cf.classify_all(extraction.calls)
    assert call.to_record() == before
