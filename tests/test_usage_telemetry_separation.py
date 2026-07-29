"""US-PM-6 AC 2: hard errors, soft errors and malformed inputs are SEPARATE.

``tests/test_usage_telemetry_classify.py`` proves each class is *detected*.
This module proves the word the criterion turns on -- **separately** -- and is
the regression net for the specific mistake two of the four studies in
``Study/`` made:

1. **Independence** -- a call carrying exactly one marker lands in exactly one
   class and contributes nothing to the other two, in the inclusive counts, the
   exclusive partition, the per-tool table and the filtered views. Deleting all
   calls of one class leaves the other two counts untouched.
2. **Arithmetic** -- two identities, asserted as identities and not as literals:

   * ``sum(exclusive[class] for class in PRECEDENCE) == failures`` and
     ``sum(exclusive.values()) == total`` (the exclusive view is a partition);
   * ``hard + soft + malformed - failures == sum(len(classes) - 1)`` over the
     failing calls (the inclusive view may exceed the total by *exactly* the
     double-counting, never by more or less), with ``failures`` itself equal to
     the number of **distinct** failing ``tool_use_id``s.
3. **Output** -- ``classify``'s text report, ``classify --json``, ``report``'s
   text report and ``report --json`` each surface the three as three distinct
   figures. Fixtures give the three classes deliberately different counts, so a
   regression that merged them into one "errors" number cannot pass.
4. **The studies' mistake** -- a metric derived from ``is_error`` alone must not
   equal the true failure rate. The reference corpus is the one from
   ``an internal usage study``: 47 hard (1.4%), 155 soft (4.7%), 27
   malformed, true rate 6.2%.
5. **Real strings** -- every error body quoted in ``Study/`` classifies the way
   the story says it does.
"""

import itertools
import json
import re

import pytest

from tools.usage_telemetry import classify as cf
from tools.usage_telemetry import report as rp
from tools.usage_telemetry.extract import ToolCall, ToolResult, scan

# --------------------------------------------------------- real Study bodies --

#: ``an internal usage study`` line 89 -- 135 of 155 soft errors on that corpus.
SOFT_NOTE_LIMIT = '{"result":"error: Run-log note must be 1024 characters or fewer"}'
#: line 90 -- 12 calls.
SOFT_NOT_READY = (
    '{"result":"error: task is not ready to grab\\nblockers:\\n'
    "- status is 'review', not 'todo'\"}"
)
#: lines 91-92, 94 -- 6 calls across pm_status / pm_docs / pm_repair.
SOFT_NO_CONFIG = '{"result":"error: No .project/config.yaml found in any parent directory"}'
#: line 95 -- 1 call.
SOFT_NO_VISION = '{"result":"error: VISION.md not found"}'
#: The harness's own overflow message: not the envelope, still a failed call.
SOFT_OVERFLOW = "Error: result (74,006 characters) exceeds maximum allowed tokens."

#: ``an internal usage study`` line 139 -- the ``__unparsedToolInput`` symptom.
HARD_UNPARSABLE = (
    "<tool_use_error>InputValidationError: mcp__projectman__pm_update was called "
    "with input that could not be parsed as JSON.\nYou sent (first 53 of 53 bytes)"
    "</tool_use_error>"
)
#: ``an internal usage study`` line 62 -- the pydantic half of the hard errors.
HARD_VALIDATION = (
    "Error executing tool pm_grab: 1 validation error for pm_grabArguments\n"
    "task_id\n  Field required [type=missing, input_value={'id': 'US-TOM-43-9'}]"
)
#: A *successful* pm_get listing whose payload merely contains ``error:``.
SUCCESS_WITH_ERROR_FIELD = (
    '{"result":"- id: US-SK-8-1\\n  error: \'Task not found: US-SK-8-1\'\\n'
    "- id: US-SK-8-2\\n  error: 'Task not found: US-SK-8-2'\"}"
)
SUCCESS_PLAIN = '{"result":"ok"}'

#: The headline counts of ``an internal usage study``, Finding 1.
SAMPLE_HARD = 47
SAMPLE_SOFT = 155
SAMPLE_MALFORMED = 27  # all 27 also carry is_error, so they are inside SAMPLE_HARD
SAMPLE_FAILURES = SAMPLE_HARD + SAMPLE_SOFT  # 202 distinct calls
SAMPLE_TOTAL = 3258  # gives 6.2% combined / 1.4% is_error-only

_ids = itertools.count()


# ------------------------------------------------------------------ builders --


def make_call(
    tool="pm_update",
    *,
    hard=False,
    soft=False,
    malformed=False,
    matched=True,
    text=None,
    session="s1",
    seq=None,
):
    """One joined call carrying exactly the requested failure markers."""
    tid = f"tu-{next(_ids)}"
    if text is None:
        text = SOFT_NOTE_LIMIT if soft else (HARD_VALIDATION if hard else SUCCESS_PLAIN)
    call = ToolCall(
        tool_use_id=tid,
        name=f"mcp__projectman__{tool}",
        input=(
            {cf.MALFORMED_INPUT_KEY: '{"id": "X", "assignee": }'}
            if malformed
            else {"id": "X"}
        ),
        timestamp="2026-07-29T00:00:00Z",
        session=session,
        session_id=session,
        project="proj",
        source_file=f"proj/{session}.jsonl",
        line_no=1,
        seq=next(_ids) if seq is None else seq,
    )
    if matched:
        call.result = ToolResult(tool_use_id=tid, is_error=hard, text=text)
    return call


def only(cls, **kwargs):
    """A call carrying exactly one failure class and no other marker."""
    return make_call(
        hard=cls == cf.HARD_ERROR,
        soft=cls == cf.SOFT_ERROR,
        malformed=cls == cf.MALFORMED_INPUT,
        **kwargs,
    )


def inclusive_counts(report):
    return {
        cf.HARD_ERROR: report.hard,
        cf.SOFT_ERROR: report.soft,
        cf.MALFORMED_INPUT: report.malformed,
    }


#: Deliberately different per class, so any merge of the three is detectable.
MIXED = {cf.HARD_ERROR: 3, cf.SOFT_ERROR: 5, cf.MALFORMED_INPUT: 7}


@pytest.fixture
def mixed():
    """3 hard-only, 5 soft-only, 7 malformed-only, 11 successes. No overlaps."""
    calls = [only(cls) for cls, n in MIXED.items() for _ in range(n)]
    calls += [make_call() for _ in range(11)]
    return cf.classify_all(calls)


@pytest.fixture
def sample():
    """The ``an internal usage study`` shape: malformed nested inside hard."""
    calls = [
        make_call(malformed=True, hard=True, text=HARD_UNPARSABLE)
        for _ in range(SAMPLE_MALFORMED)
    ]
    calls += [make_call(hard=True) for _ in range(SAMPLE_HARD - SAMPLE_MALFORMED)]
    calls += [make_call(soft=True) for _ in range(SAMPLE_SOFT)]
    calls += [make_call() for _ in range(SAMPLE_TOTAL - SAMPLE_FAILURES)]
    return cf.classify_all(calls)


@pytest.fixture
def corpus(tmp_path):
    """On-disk transcript: one call of each class plus one success, 100% joined."""
    cases = [
        ("pm_get", {"id": "A"}, SUCCESS_WITH_ERROR_FIELD, False),
        ("pm_update", {"id": "B", "note": "x" * 2000}, SOFT_NOTE_LIMIT, False),
        ("pm_grab", {"id": "C"}, HARD_VALIDATION, True),
        (
            "pm_create_task",
            {cf.MALFORMED_INPUT_KEY: '{"title": }'},
            SUCCESS_PLAIN,
            False,
        ),
    ]
    records = []
    for i, (tool, tool_input, text, is_error) in enumerate(cases):
        tid = f"c-{i}"
        for block in (
            {
                "type": "tool_use",
                "id": tid,
                "name": f"mcp__projectman__{tool}",
                "input": tool_input,
            },
            {
                "type": "tool_result",
                "tool_use_id": tid,
                "content": text,
                "is_error": is_error,
            },
        ):
            records.append(
                {
                    "type": "assistant",
                    "sessionId": "sess-a",
                    "timestamp": "2026-07-29T00:00:00Z",
                    "message": {"content": [block]},
                }
            )
    path = tmp_path / "proj" / "sess-a.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return tmp_path


# ----------------------------------------------- 1. independent identifiability --


@pytest.mark.parametrize("cls", [cf.HARD_ERROR, cf.SOFT_ERROR, cf.MALFORMED_INPUT])
def test_a_call_in_one_class_only_never_leaks_into_the_other_two(cls):
    """ONLY hard / ONLY soft / ONLY malformed each land in exactly their class."""
    report = cf.classify_all([only(cls)])
    others = [c for c in cf.PRECEDENCE if c != cls]

    counts = inclusive_counts(report)
    assert counts[cls] == 1
    assert [counts[c] for c in others] == [0, 0]

    exclusive = report.primary_counts
    assert exclusive[cls] == 1
    assert [exclusive[c] for c in others] == [0, 0]

    item = report.classified[0]
    assert item.classes == (cls,)
    assert item.primary == cls
    assert len(report.failing(cls)) == 1
    assert [len(report.failing(c)) for c in others] == [0, 0]
    assert report.failures == 1


def test_each_class_is_counted_independently_in_a_mixed_corpus(mixed):
    """Three different counts, so a merged "errors" number cannot reproduce them."""
    assert inclusive_counts(mixed) == MIXED
    assert mixed.primary_counts == {
        cf.MALFORMED_INPUT: 7,
        cf.HARD_ERROR: 3,
        cf.SOFT_ERROR: 5,
        cf.SUCCESS: 11,
        cf.UNMATCHED: 0,
    }
    assert mixed.overlaps == {}
    assert mixed.failures == 15
    assert len({mixed.hard, mixed.soft, mixed.malformed}) == 3


@pytest.mark.parametrize("dropped", [cf.HARD_ERROR, cf.SOFT_ERROR, cf.MALFORMED_INPUT])
def test_removing_one_class_leaves_the_other_two_counts_untouched(mixed, dropped):
    """The counters are independent, not derived from one another."""
    kept = [c.call for c in mixed.classified if dropped not in c.classes]
    after = cf.classify_all(kept)

    assert inclusive_counts(after)[dropped] == 0
    for other in (c for c in cf.PRECEDENCE if c != dropped):
        assert inclusive_counts(after)[other] == MIXED[other]
    assert after.failures == mixed.failures - MIXED[dropped]


def test_per_tool_table_keeps_the_three_classes_in_separate_columns():
    report = cf.classify_all(
        [
            only(cf.HARD_ERROR, tool="pm_update"),
            only(cf.SOFT_ERROR, tool="pm_update"),
            only(cf.MALFORMED_INPUT, tool="pm_update"),
            only(cf.SOFT_ERROR, tool="pm_grab"),
        ]
    )
    row = report.by_tool()["pm_update"]
    assert (row.hard, row.soft, row.malformed) == (1, 1, 1)
    assert row.failures == 3
    grab = report.by_tool()["pm_grab"]
    assert (grab.hard, grab.soft, grab.malformed) == (0, 1, 0)


def test_soft_error_detection_is_independent_of_is_error():
    """The same body classifies soft whether or not the transport flagged it."""
    quiet = cf.classify(make_call(soft=True))
    loud = cf.classify(make_call(soft=True, hard=True))
    assert quiet.soft and loud.soft
    assert not quiet.hard and loud.hard
    assert quiet.primary == cf.SOFT_ERROR and loud.primary == cf.HARD_ERROR


def test_malformed_detection_is_independent_of_the_response():
    """``__unparsedToolInput`` is read off the input, never off the result body."""
    for kwargs in ({}, {"hard": True}, {"soft": True}, {"matched": False}):
        assert cf.classify(make_call(malformed=True, **kwargs)).malformed


# ------------------------------------------------------- 2. arithmetic identities --


@pytest.mark.parametrize(
    "malformed,hard,soft", list(itertools.product([False, True], repeat=3))
)
def test_both_arithmetic_identities_hold_for_every_marker_combination(
    malformed, hard, soft
):
    calls = [make_call(malformed=malformed, hard=hard, soft=soft) for _ in range(3)]
    calls += [make_call() for _ in range(2)]
    calls += [make_call(matched=False)]
    report = cf.classify_all(calls)
    exclusive = report.primary_counts

    # Identity 1: the exclusive view is a partition of the corpus, and its
    # failure classes sum to exactly the distinct failure total.
    assert sum(exclusive.values()) == report.total
    assert sum(exclusive[c] for c in cf.PRECEDENCE) == report.failures

    # Identity 2: the inclusive view may exceed that total, by exactly the
    # number of extra classes the overlapping calls carry -- never more.
    inclusive_sum = report.hard + report.soft + report.malformed
    assert inclusive_sum >= report.failures
    assert inclusive_sum - report.failures == sum(
        len(c.classes) - 1 for c in report.failing()
    )


def test_combined_failure_total_counts_distinct_calls(sample):
    """``failures`` is |set of failing calls|, never a sum over the classes."""
    assert sample.failures == len({c.call.tool_use_id for c in sample.failing()})
    assert sample.failures == SAMPLE_FAILURES
    assert sample.hard + sample.soft + sample.malformed == SAMPLE_FAILURES + SAMPLE_MALFORMED
    assert sample.failure_rate == pytest.approx(SAMPLE_FAILURES / SAMPLE_TOTAL)


def test_exclusive_counts_sum_exactly_to_the_distinct_failure_total(sample):
    exclusive = sample.primary_counts
    assert sum(exclusive[c] for c in cf.PRECEDENCE) == sample.failures
    assert sum(exclusive.values()) == sample.total
    # The 27 overlapping calls are attributed to malformed, so exclusive hard
    # is 20 while inclusive hard stays 47 -- neither number is lost.
    assert exclusive[cf.MALFORMED_INPUT] == SAMPLE_MALFORMED
    assert exclusive[cf.HARD_ERROR] == SAMPLE_HARD - SAMPLE_MALFORMED
    assert exclusive[cf.SOFT_ERROR] == SAMPLE_SOFT
    assert sample.hard == SAMPLE_HARD


def test_inclusive_counts_exceed_the_total_only_by_the_overlap(sample):
    inclusive_sum = sample.hard + sample.soft + sample.malformed
    assert inclusive_sum > sample.failures
    assert inclusive_sum - sample.failures == SAMPLE_MALFORMED
    assert sample.overlaps == {"malformed_input+hard_error": SAMPLE_MALFORMED}


def test_no_double_counting_when_a_call_carries_all_three_classes():
    report = cf.classify_all(
        [make_call(malformed=True, hard=True, soft=True), make_call()]
    )
    assert (report.hard, report.soft, report.malformed) == (1, 1, 1)
    assert report.failures == 1  # one call, not three
    assert report.primary_counts[cf.MALFORMED_INPUT] == 1
    assert report.primary_counts[cf.HARD_ERROR] == 0
    assert report.primary_counts[cf.SOFT_ERROR] == 0
    assert report.overlaps == {"malformed_input+hard_error+soft_error": 1}


def test_successes_and_unmatched_complete_the_partition(mixed):
    assert mixed.successes + mixed.failures + mixed.unmatched == mixed.total


# --------------------------------------------------------- 3. the output layer --


def _section(text, header):
    """The indented lines of one block of a text report, as ``label -> number``."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    parsed = {}
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        match = re.match(r"\s+(\S.*?)\s{2,}([\d,]+)\b", line)
        if match:
            parsed[match.group(1).strip()] = int(match.group(2).replace(",", ""))
    return parsed


def test_classify_text_report_shows_three_distinct_inclusive_figures(mixed):
    block = _section(cf.format_report(mixed), "failure classes (inclusive")
    assert block["hard errors"] == 3
    assert block["soft errors"] == 5
    assert block["malformed inputs"] == 7
    assert block["COMBINED (distinct)"] == 15
    # A regression that printed one merged "errors" figure would repeat a value.
    assert len({block["hard errors"], block["soft errors"], block["malformed inputs"]}) == 3


def test_classify_text_report_shows_the_exclusive_view_as_its_own_block(sample):
    text = cf.format_report(sample)
    inclusive = _section(text, "failure classes (inclusive")
    exclusive = _section(text, "primary class (exclusive")

    assert inclusive["hard errors"] == SAMPLE_HARD
    assert exclusive["hard errors"] == SAMPLE_HARD - SAMPLE_MALFORMED
    assert exclusive["malformed inputs"] == SAMPLE_MALFORMED
    assert inclusive["COMBINED (distinct)"] == SAMPLE_FAILURES
    assert (
        exclusive["hard errors"] + exclusive["soft errors"] + exclusive["malformed inputs"]
        == inclusive["COMBINED (distinct)"]
    )


def test_classify_json_exposes_the_three_as_distinct_fields(mixed):
    payload = mixed.as_dict()
    assert payload["inclusive"] == {"hard_error": 3, "soft_error": 5, "malformed_input": 7}
    assert set(payload["rates"]) == {
        "hard_error",
        "soft_error",
        "malformed_input",
        "combined_failure_rate",
    }
    assert payload["exclusive"][cf.HARD_ERROR] == 3
    assert payload["exclusive"][cf.SOFT_ERROR] == 5
    assert payload["exclusive"][cf.MALFORMED_INPUT] == 7
    assert payload["failures"] == 15
    # No merged "errors" figure anywhere at the top level.
    assert "errors" not in payload
    assert payload["failures"] != payload["inclusive"]["hard_error"]


def test_usage_report_text_breaks_the_failure_total_into_the_three_classes(mixed):
    """report.py's text output must not collapse the classes into one number."""
    usage = rp.build_report([c.call for c in mixed.classified], classification=mixed)
    text = rp.format_usage_report(usage)
    line = next(ln for ln in text.splitlines() if ln.startswith("failures"))
    assert "15" in line

    block = _section(text, "failures")
    assert block["hard errors"] == 3
    assert block["soft errors"] == 5
    assert block["malformed inputs"] == 7
    assert cf.MALFORMED_INPUT_KEY in text


def test_usage_report_json_exposes_the_three_classes_separately(mixed):
    usage = rp.build_report([c.call for c in mixed.classified], classification=mixed)
    payload = usage.as_dict()["failures"]
    assert payload["inclusive"] == {"hard_error": 3, "soft_error": 5, "malformed_input": 7}
    assert payload["exclusive"][cf.MALFORMED_INPUT] == 7
    assert payload["failures"] == 15


def test_classify_cli_text_and_json_keep_the_three_separate(corpus, capsys):
    assert cf.main(["--root", str(corpus)]) == 0
    text = capsys.readouterr().out
    block = _section(text, "failure classes (inclusive")
    assert (block["hard errors"], block["soft errors"], block["malformed inputs"]) == (
        1,
        1,
        1,
    )
    assert block["COMBINED (distinct)"] == 3

    assert cf.main(["--root", str(corpus), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["inclusive"] == {
        "hard_error": 1,
        "soft_error": 1,
        "malformed_input": 1,
    }
    assert payload["failures"] == 3
    assert payload["total_calls"] == 4


def test_report_cli_text_and_json_keep_the_three_separate(corpus, capsys):
    assert rp.main(["--root", str(corpus)]) == 0
    block = _section(capsys.readouterr().out, "failures")
    assert (block["hard errors"], block["soft errors"], block["malformed inputs"]) == (
        1,
        1,
        1,
    )

    assert rp.main(["--root", str(corpus), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)["failures"]
    assert payload["inclusive"] == {
        "hard_error": 1,
        "soft_error": 1,
        "malformed_input": 1,
    }
    assert payload["failures"] == 3


# ------------------------------------------------------- 4. the studies' mistake --


def test_is_error_alone_does_not_equal_the_true_failure_rate(sample):
    """Two of the four studies quoted ~1% because they stopped at ``is_error``."""
    is_error_only_rate = sample.hard_rate
    assert is_error_only_rate == pytest.approx(SAMPLE_HARD / SAMPLE_TOTAL)
    assert is_error_only_rate == pytest.approx(0.014, abs=0.001)

    assert sample.failure_rate == pytest.approx(0.062, abs=0.001)
    assert sample.failure_rate != is_error_only_rate
    assert sample.failure_rate > 4 * is_error_only_rate


def test_soft_errors_are_part_of_the_combined_total(sample):
    """Fails the moment soft errors stop being counted."""
    assert sample.soft == SAMPLE_SOFT
    assert sample.failures - sample.hard == SAMPLE_SOFT
    assert sample.soft_rate == pytest.approx(SAMPLE_SOFT / SAMPLE_TOTAL)
    assert sample.soft > sample.hard


def test_dropping_soft_detection_collapses_the_rate_to_the_studies_wrong_number(
    monkeypatch, sample
):
    """Simulates the studies' method and shows the metric is sensitive to it."""
    calls = [c.call for c in sample.classified]
    monkeypatch.setattr(cf, "SOFT_ERROR_PATTERNS", ())
    broken = cf.classify_all(calls)

    assert broken.soft == 0
    assert broken.failures == SAMPLE_HARD
    assert broken.failure_rate == pytest.approx(broken.hard_rate)
    assert sample.failure_rate > 4 * broken.failure_rate


def test_malformed_inputs_stay_visible_although_they_are_also_hard_errors(sample):
    """Attributing the 27 to "hard error" would hide the one fixable cause."""
    assert sample.malformed == SAMPLE_MALFORMED
    assert sample.primary_counts[cf.MALFORMED_INPUT] == SAMPLE_MALFORMED
    assert sample.malformed_rate == pytest.approx(SAMPLE_MALFORMED / SAMPLE_TOTAL)
    assert len(sample.failing(cf.MALFORMED_INPUT)) == SAMPLE_MALFORMED


def test_a_failure_rate_built_from_hard_alone_is_not_the_reported_rate(corpus):
    extraction = scan(root=corpus)
    report = cf.classify_all(extraction.calls)
    hard_only = sum(1 for c in extraction.calls if c.result and c.result.is_error)
    assert hard_only == 1
    assert report.failures == 3
    assert report.failure_rate == pytest.approx(3 / 4)


# ------------------------------------------------------- 5. real observed bodies --


@pytest.mark.parametrize(
    "label,text,is_error,malformed,expected",
    [
        ("run-log note cap", SOFT_NOTE_LIMIT, False, False, cf.SOFT_ERROR),
        ("not ready to grab", SOFT_NOT_READY, False, False, cf.SOFT_ERROR),
        ("no config.yaml", SOFT_NO_CONFIG, False, False, cf.SOFT_ERROR),
        ("no VISION.md", SOFT_NO_VISION, False, False, cf.SOFT_ERROR),
        ("result too large", SOFT_OVERFLOW, False, False, cf.SOFT_ERROR),
        ("InputValidationError", HARD_UNPARSABLE, True, False, cf.HARD_ERROR),
        ("pydantic validation", HARD_VALIDATION, True, False, cf.HARD_ERROR),
        ("__unparsedToolInput", HARD_UNPARSABLE, True, True, cf.MALFORMED_INPUT),
        ("pm_get error field", SUCCESS_WITH_ERROR_FIELD, False, False, cf.SUCCESS),
    ],
)
def test_real_study_bodies_classify_as_the_story_says(
    label, text, is_error, malformed, expected
):
    item = cf.classify(make_call(hard=is_error, malformed=malformed, text=text))
    assert item.primary == expected, label
    if expected == cf.SOFT_ERROR:
        assert item.soft and not item.hard and not item.malformed
    if expected == cf.SUCCESS:
        assert not item.failed


def test_the_studys_soft_error_table_reproduces_exactly():
    """``an internal usage study`` Finding 1, the per-tool soft-error table."""
    table = [
        ("pm_update", SOFT_NOTE_LIMIT, 135),
        ("pm_grab", SOFT_NOT_READY, 12),
        ("pm_status", SOFT_NO_CONFIG, 3),
        ("pm_docs", SOFT_NO_CONFIG, 2),
        ("pm_done_next", SOFT_NOTE_LIMIT, 1),
        ("pm_repair", SOFT_NO_CONFIG, 1),
        ("pm_docs", SOFT_NO_VISION, 1),
    ]
    calls = [
        make_call(tool=tool, soft=True, text=text)
        for tool, text, count in table
        for _ in range(count)
    ]
    report = cf.classify_all(calls)

    assert report.soft == SAMPLE_SOFT
    assert report.hard == 0
    assert report.malformed == 0
    assert report.top_messages(3) == [
        ("pm_update", "Run-log note must be 1024 characters or fewer", 135),
        ("pm_grab", "task is not ready to grab", 12),
        ("pm_status", "No .project/config.yaml found in any parent directory", 3),
    ]


def test_the_malformed_key_is_read_from_the_input_not_the_body():
    """``an internal usage study``: 45 calls, all found via the input key."""
    calls = [make_call(malformed=True, hard=True, text=HARD_UNPARSABLE) for _ in range(45)]
    calls += [make_call() for _ in range(2000 - 45)]
    report = cf.classify_all(calls)
    assert report.malformed == 45
    assert report.malformed_rate == pytest.approx(0.0225, abs=0.0005)
    assert report.primary_counts[cf.MALFORMED_INPUT] == 45
    assert report.primary_counts[cf.HARD_ERROR] == 0
