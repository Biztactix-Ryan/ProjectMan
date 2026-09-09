"""US-PM-53-7 — the orchestrate skill dispatches two lanes, tracked by lane.

Story US-PM-53's scheduling half: the orchestrator may keep *two* independent
tasks in flight, one per lane, so it validates and merges one lane's returned
work while the other lane's worker is still running instead of idling for the
20–100 minutes a long task takes.

What the skill has to say, and what is pinned here:

* **the flag** — ``--lanes <1|2>``, default 1, in the ``args:`` usage line the
  CLI prints *and* in the Flags section.  A flag documented in only one of the
  two is a flag the reader meets by accident.
* **where lane B's task comes from** — ``pm_board(lane_compatible_with=<lane
  A's task>)``, the filter US-PM-53-6 added, taking its first ``available``
  entry in plan order.  Independence is decided by the store, never by the
  orchestrator's memory of what the two tasks touch, and the same call is what
  keeps a task whose dependency is still in flight out of the second lane.
* **at most two claims** — one per lane, keyed by run id and lane, each
  carrying its task, its ``<tb>`` and whether its worker has returned.  A skill
  that says "dispatch two" without saying *what it tracks* cannot tell which
  lane a returning worker belongs to.
* **background dispatch** — both lanes go out as background ``Agent``s, which
  is the whole point: a foreground dispatch blocks the orchestrator until the
  worker returns and there is no second lane to speak of.
* **counting across lanes** — ``--max`` counts dispatches and the step 21
  health check counts accepted tasks over both lanes, not per lane.
* **either lane on the way out** — Stop Conditions releases *any* pre-claimed
  unstarted task, in either lane, rather than assuming one in-flight claim.

US-PM-53-8 added the loop those claims run in, and it is pinned below the
US-PM-53-7 clauses:

* **first back, first handled** — the orchestrator waits for whichever worker's
  notification lands first and takes that lane through steps 16-19 while the
  other worker keeps running, then refills the freed lane and waits again.  One
  lane is validated or merged at a time: two concurrent validations would put
  both workers' output back into the context the lanes exist to protect.
* **acceptance order, never dispatch order** — the second lane's branch was cut
  from ``<rb>`` before the first lane's merge, so its merge may conflict.  That
  is expected, and it is handled by US-PM-51-8's conflict path: abort,
  ``pm_retry`` with the conflicting paths in ``evidence.files`` and the "rebase
  onto ``<rb>``" note, and a park on the second conflict.  A task retried for a
  conflict keeps its lane and its ``<tb>`` and is not a fresh dispatch, so it
  cannot silently spend ``--max``.
* **the validator knows what it does not own** — with two lanes it is told the
  other in-flight task, whose files are out of scope; a diff that reaches into
  them is a retry, not a park.

Template, tracked render and live render are all checked, so a template edit
that skips the regeneration is caught here rather than shipped.  The
falsification guard below the clause table is the other half: the single-lane
skill this task started from must be *rejected* by these very clauses.

US-PM-53-9 wrote the reasoning down — ``docs/reference/orchestrate-design.md``
gained a ``## Lanes`` section and ``docs/reference/skills.md`` a lanes
paragraph in its ``/pm-orchestrate`` entry — and the last block of this file
pins it.  The skill is instruction and the doc is the argument, so a clause
deleted from the doc is a rule nobody can check the skill against afterwards:
what a lane may not share (the four store-side compatibility rules), why the
answer is two and not three, the merge-order rule with the conflict path it
reuses, the dependency barrier, the validator's out-of-scope line, and the
single-lane default.
"""

import re

import pytest
import yaml

from projectman.cli import _render_template
from tests.test_orchestrate_skill_size import DESIGN_DOC, REPO_ROOT, design_section
from tests.test_skill_verdict_verbs import (
    ORCHESTRATE_TEMPLATE_NAME,
    DOCS,
    _text,
)

#: the user-facing catalogue entry, where a reader meets the flag first
SKILLS_DOC = REPO_ROOT / "docs" / "reference" / "skills.md"

#: the flag, as it is spelled everywhere
LANES_FLAG = "--lanes"

#: ``--lanes <1|2>`` — the flag with its value set
LANES_WITH_VALUES = re.compile(r"--lanes\s*<1\|2>")

#: the default, stated in the Flags entry
DEFAULT_ONE = re.compile(r"default\s*1\b", re.IGNORECASE)

#: US-PM-53-6's board filter — where lane B's candidate comes from
LANE_FILTER = re.compile(r"pm_board\(lane_compatible_with=")

#: the second lane, by the name the skill gives it
LANE_B = re.compile(r"\blane B\b|\bB\b")

#: what a lane's claim record carries
CLAIM_FIELDS = [
    re.compile(r"claim per lane|one claim each|two claims"),
    re.compile(r"`<tb>`"),
    re.compile(r"return"),
]

#: dispatched without blocking on the worker
BACKGROUND = re.compile(r"\bbackground\b", re.IGNORECASE)

#: "both lanes", "across both lanes", "either lane" — counted over the pair
BOTH_LANES = re.compile(r"both lanes|across (?:both )?lanes|either lane", re.IGNORECASE)

#: the release on the way out, which must not assume a single claim
EITHER_LANE = re.compile(r"either lane", re.IGNORECASE)


# ─── slicing helpers ─────────────────────────────────────────────


def _section(text: str, heading: str) -> str:
    """The block under a ``## `` heading, up to the next one."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(heading)]
    assert starts, f"no {heading!r} heading"
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _step(text: str, prefix: str) -> str:
    """Numbered step ``prefix``, from its line to the next numbered line."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if line.startswith(prefix)]
    assert starts, f"no line starting with {prefix!r} — that step vanished"
    start = starts[0]
    end = next(
        (
            n
            for n in range(start + 1, len(lines))
            if re.match(r"^\d+(?:-\d+)?\.\s", lines[n]) or lines[n].startswith("## ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def _args_line(text: str) -> str:
    return yaml.safe_load(text.split("---")[1])["args"]


def _flags(text: str) -> str:
    return _section(text, "## Flags")


def _execution(text: str) -> str:
    return _section(text, "## Phase 3")


def _stop_conditions(text: str) -> str:
    return _section(text, "## Stop Conditions")


# ─── the criterion, clause by clause ─────────────────────────────
#
# Each clause takes the whole document so the falsification guard can strip the
# lanes out of a real render and push the result through the same checks.


def _args_line_advertises_lanes(text: str) -> bool:
    """The usage string the CLI prints names the flag with its two values."""
    return bool(LANES_WITH_VALUES.search(_args_line(text)))


def _flags_entry_gives_the_default(text: str) -> bool:
    """A Flags bullet spells ``--lanes <1|2>`` and says the default is 1."""
    bullets = [
        line
        for line in _flags(text).splitlines()
        if line.startswith("- ") and LANES_FLAG in line
    ]
    if not bullets:
        return False
    return bool(LANES_WITH_VALUES.search(bullets[0]) and DEFAULT_ONE.search(bullets[0]))


def _lane_b_comes_from_the_board_filter(text: str) -> bool:
    """Lane B's candidate is chosen by the store, through US-PM-53-6's filter."""
    lines = [
        line for line in _execution(text).splitlines() if LANE_FILTER.search(line)
    ]
    return bool(lines) and any(LANE_B.search(line) for line in lines)


def _lane_b_idles_when_nothing_is_compatible(text: str) -> bool:
    """No compatible task is not an error: the lane waits for lane A."""
    flat = " ".join(_execution(text).split()).lower()
    return "idle" in flat and "accept" in flat


def _a_dependency_in_flight_is_barred(text: str) -> bool:
    """One clause saying the store already excludes an in-flight dependency."""
    flat = " ".join(_execution(text).split()).lower()
    return "in-flight dependency" in flat or "dependency in flight" in flat


def _tracks_one_claim_per_lane(text: str) -> bool:
    """Two claims, keyed by lane, each with its task, branch and return state."""
    execution = _execution(text)
    if "run id" not in execution.lower():
        return False
    return all(pattern.search(execution) for pattern in CLAIM_FIELDS)


def _dispatches_in_the_background(text: str) -> bool:
    """Step 15 sends the worker off without blocking the orchestrator."""
    return bool(BACKGROUND.search(_step(text, "15.")))


def _max_counts_across_lanes(text: str) -> bool:
    """``--max`` is a run budget, not a per-lane one."""
    return bool(BOTH_LANES.search(_step(text, "13.")))


def _health_check_counts_across_lanes(text: str) -> bool:
    """So is the every-3-accepted-tasks audit poll."""
    step = _step(text, "21.")
    return bool(BOTH_LANES.search(step)) and "every 3 accepted tasks" in step


def _stop_releases_either_lane(text: str) -> bool:
    """Phase 4's release covers whichever lane holds an unstarted claim."""
    stop = _stop_conditions(text)
    return bool(EITHER_LANE.search(stop)) and "pm_release(" in stop


def _a_returned_lane_is_validated_and_merged(text: str) -> bool:
    """US-PM-53-8 expands this; the skill must already carry the sentence."""
    flat = " ".join(_execution(text).split()).lower()
    return "16-19" in flat and "merge" in flat and "first" in flat


# ─── US-PM-53-8: the loop the two claims run in ──────────────────

#: the notification the background dispatch returns on
FIRST_BACK = re.compile(
    r"(?:first|whichever)[^.\n]{0,60}notification[^.\n]{0,60}|"
    r"notification[^.\n]{0,40}(?:first|lands first)",
    re.IGNORECASE,
)

#: one lane at a time in validation and in the merge
ONE_AT_A_TIME = re.compile(
    r"one lane[^.\n]{0,40}(?:validated|merged)[^.\n]{0,30}at a time", re.IGNORECASE
)

#: the freed lane is filled again, from the picking steps
REFILL = re.compile(r"refill[^.\n]{0,60}11", re.IGNORECASE)

#: the merge-order rule itself
MERGE_ORDER = re.compile(
    r"acceptance order[^.\n]{0,40}(?:never|not)\s+dispatch order", re.IGNORECASE
)

#: why the second lane's merge can conflict at all
CUT_BEFORE_THE_MERGE = re.compile(
    r"cut before[^.\n]{0,40}merge|before[^.\n]{0,20}merge[^.\n]{0,40}conflict",
    re.IGNORECASE,
)

#: US-PM-51-8's conflict path, which the rule reuses rather than restates
CONFLICT_PATH = [
    re.compile(r"merge --abort"),
    re.compile(r"pm_retry"),
    re.compile(r"evidence\.files"),
    re.compile(r"rebase onto"),
    re.compile(r"second conflict parks", re.IGNORECASE),
]

#: a conflict retry is the same lane and branch, not a new dispatch
RETRY_KEEPS_ITS_LANE = re.compile(
    r"keeps its lane[^.\n]{0,40}`<tb>`", re.IGNORECASE
)
NOT_A_NEW_DISPATCH = re.compile(
    r"not a new dispatch[^.\n]{0,20}`--max`", re.IGNORECASE
)

#: what the validator is told about the lane it is not validating
OTHER_LANE_OUT_OF_SCOPE = re.compile(
    r"other lane[^\n]{0,60}out of scope", re.IGNORECASE
)
TOUCHING_THEM_IS_A_RETRY = re.compile(
    r"retry, not a park", re.IGNORECASE
)


def _validator_fence(text: str) -> str:
    """The Validator Prompt Template's fenced block."""
    blocks = re.findall(r"```\n(.*?)```", text, re.DOTALL)
    fences = [b for b in blocks if "Validate task <task-id>" in b]
    assert len(fences) == 1, f"expected one validator fence, found {len(fences)}"
    return fences[0]


def _handles_the_first_notification_to_land(text: str) -> bool:
    """Neither lane is privileged: the loop turns on whichever worker returns."""
    execution = _execution(text)
    return bool(FIRST_BACK.search(execution)) and "16-19" in execution


def _validates_one_lane_at_a_time(text: str) -> bool:
    """The other worker keeps running; its output is not being read yet."""
    execution = _execution(text)
    return bool(ONE_AT_A_TIME.search(execution)) and bool(
        re.search(r"other worker[^.\n]{0,20}runs?", execution, re.IGNORECASE)
    )


def _refills_the_freed_lane(text: str) -> bool:
    """A handled lane goes back to the picking steps, judged against the other."""
    execution = _execution(text)
    return bool(REFILL.search(execution)) and "in flight" in execution.lower()


def _merges_in_acceptance_order(text: str) -> bool:
    """The merge-order rule, stated as a rule and not implied by step order."""
    accept = _accept_bullet(text)
    return bool(MERGE_ORDER.search(accept)) and bool(CUT_BEFORE_THE_MERGE.search(accept))


def _keeps_the_conflict_path(text: str) -> bool:
    """US-PM-51-8's path is reused whole: abort, retry with paths, then park."""
    accept = _accept_bullet(text)
    return all(pattern.search(accept) for pattern in CONFLICT_PATH)


def _a_conflict_retry_is_not_a_new_dispatch(text: str) -> bool:
    """Same lane, same branch, and it does not spend ``--max``."""
    accept = _accept_bullet(text)
    return bool(RETRY_KEEPS_ITS_LANE.search(accept)) and bool(
        NOT_A_NEW_DISPATCH.search(accept)
    )


def _validator_is_told_the_other_in_flight_task(text: str) -> bool:
    """With two lanes, the other lane's files are out of scope for this verdict."""
    fence = _validator_fence(text)
    return bool(OTHER_LANE_OUT_OF_SCOPE.search(fence)) and bool(
        TOUCHING_THEM_IS_A_RETRY.search(fence)
    )


def _accept_bullet(text: str) -> str:
    """Step 19's **Accept** bullet — where the merge and its conflicts live."""
    bullets = [
        line for line in text.splitlines() if line.strip().startswith("- **Accept**:")
    ]
    assert len(bullets) == 1, f"expected one **Accept** bullet, found {len(bullets)}"
    return bullets[0]


CLAUSES = {
    "args line advertises --lanes <1|2>": _args_line_advertises_lanes,
    "Flags entry gives the default of 1": _flags_entry_gives_the_default,
    "lane B comes from pm_board(lane_compatible_with=)": _lane_b_comes_from_the_board_filter,
    "lane B idles when nothing is compatible": _lane_b_idles_when_nothing_is_compatible,
    "a dependency in flight is barred": _a_dependency_in_flight_is_barred,
    "tracks one claim per lane": _tracks_one_claim_per_lane,
    "dispatches in the background": _dispatches_in_the_background,
    "--max counts across lanes": _max_counts_across_lanes,
    "health check counts across lanes": _health_check_counts_across_lanes,
    "stop conditions release either lane": _stop_releases_either_lane,
    "a returned lane is validated and merged": _a_returned_lane_is_validated_and_merged,
    "handles the first notification to land": _handles_the_first_notification_to_land,
    "validates one lane at a time": _validates_one_lane_at_a_time,
    "refills the freed lane": _refills_the_freed_lane,
    "merges in acceptance order": _merges_in_acceptance_order,
    "keeps the conflict path": _keeps_the_conflict_path,
    "a conflict retry is not a new dispatch": _a_conflict_retry_is_not_a_new_dispatch,
    "validator is told the other in-flight task": _validator_is_told_the_other_in_flight_task,
}


@pytest.mark.parametrize("path", DOCS)
@pytest.mark.parametrize("clause", list(CLAUSES), ids=list(CLAUSES))
def test_the_skill_satisfies_each_lane_clause(path, clause):
    """The task's DoD, one clause per case, on template and tracked render."""
    text = _text(path)
    assert CLAUSES[clause](text), f"{path.name} fails: {clause}\n\n{_execution(text)}"


def test_the_live_render_carries_the_lanes():
    """The render an agent actually loads, not only the files on disk."""
    rendered = _render_template(ORCHESTRATE_TEMPLATE_NAME)
    failed = [name for name, check in CLAUSES.items() if not check(rendered)]
    assert not failed, f"rendered {ORCHESTRATE_TEMPLATE_NAME} fails: {failed}"


@pytest.mark.parametrize("path", DOCS)
def test_at_most_two_lanes_are_offered(path):
    """``--lanes 3`` is not a thing: the flag's values are 1 and 2.

    Two is a decision (merge order stays tractable, the orchestrator has one
    validation to run at a time), not a placeholder for "as many as you like".
    """
    text = _text(path)
    assert not re.search(r"--lanes\s*<?\d*\|?3", text), (
        f"{path.name} offers a third lane; the flag takes 1 or 2"
    )


def test_the_clause_checks_reject_the_single_lane_skill():
    """Falsification guard: the pre-US-PM-53-7 shape must be rejected.

    The mutation strips the flag and the lane wording out of the real render,
    which is what the skill looked like before this task.  If the clauses
    passed on that, they would be pinning nothing.
    """
    text = _render_template(ORCHESTRATE_TEMPLATE_NAME)
    single = re.sub(r"\s*\[--lanes <1\|2>\]", "", text)
    single = "\n".join(
        line for line in single.splitlines() if not line.startswith("- `--lanes")
    )
    single = re.sub(r"pm_board\(lane_compatible_with=[^)]*\)", "pm_board", single)
    single = re.sub(r"both lanes|either lane|lane B|per lane", "", single)
    single = single.replace("in the background", "in the foreground")
    assert single != text, "the mutation did not apply — guard is inconclusive"

    failed = {name for name, check in CLAUSES.items() if not check(single)}
    for expected in (
        "args line advertises --lanes <1|2>",
        "Flags entry gives the default of 1",
        "lane B comes from pm_board(lane_compatible_with=)",
        "dispatches in the background",
        "--max counts across lanes",
        "health check counts across lanes",
        "stop conditions release either lane",
    ):
        assert expected in failed, (
            f"a single-lane skill still satisfied {expected!r} — "
            "that clause is not pinning the lanes"
        )


# ─── US-PM-53-9: the reasoning, in the reference docs ────────────
#
# ``orchestrate-design.md`` is where an orchestrating agent goes to find out
# what a rule protects.  These checks pin the *substance* of the Lanes section
# rather than its wording where they can, and where a phrase is pinned it is a
# phrase the skill also depends on ("acceptance order, never dispatch order").


def _lanes() -> str:
    """The design doc's ``## Lanes`` section, whitespace-normalised."""
    return _norm(design_section("## Lanes"))


def _norm(text: str) -> str:
    """Collapse runs of whitespace so a phrase can span a wrapped line."""
    return re.sub(r"\s+", " ", text)


def _skills_orchestrate_section() -> str:
    """The ``## /pm-orchestrate`` entry of the skills catalogue."""
    return _norm(_section(SKILLS_DOC.read_text(encoding="utf-8"), "## /pm-orchestrate"))


def test_design_doc_has_a_lanes_section_after_the_isolation_model():
    """Placement is the argument's order: what is isolated, then what may overlap."""
    text = DESIGN_DOC.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert "Lanes" in headings, (
        f"{DESIGN_DOC} has no `## Lanes` section; two-lane dispatch shipped in "
        "US-PM-53 and the skill carries only the instruction half"
    )
    assert headings[headings.index("Isolation model") + 1] == "Lanes", (
        "the Lanes section must follow Isolation model — it refines the "
        f"isolation that section establishes; headings are {headings}"
    )


#: the four store-side rules of ``deps.lane_compatible``, each by its substance
COMPATIBILITY_RULES = [
    pytest.param(["different stories"], id="rule-1-different-stories"),
    pytest.param(
        ["Neither task depends on the other", "either direction"],
        id="rule-2-no-task-to-task-dependency-either-way",
    ),
    pytest.param(
        ["depends on the other's story", "`depends_on` may name a story"],
        id="rule-3-no-task-to-story-dependency",
    ),
    pytest.param(
        ["stories are not connected by `depends_on`", "transitively"],
        id="rule-4-no-transitive-story-to-story-path",
    ),
]


@pytest.mark.parametrize("phrases", COMPATIBILITY_RULES)
def test_the_lanes_section_names_each_compatibility_rule(phrases):
    section = _lanes()
    for phrase in phrases:
        assert phrase.lower() in section.lower(), (
            f"the Lanes section of {DESIGN_DOC} never says {phrase!r} — all "
            "four rules of `deps.lane_compatible` have to be written down, or "
            "the next reader re-derives them from the code"
        )


def test_the_lanes_section_says_compatibility_is_read_from_the_store():
    """Never from the orchestrator's memory of what two tasks touch."""
    section = _lanes()
    assert "lane_compatible" in section and "pm_board(lane_compatible_with=" in section, (
        "the Lanes section does not name `deps.lane_compatible` or the "
        "`pm_board(lane_compatible_with=)` filter it is reached through"
    )
    assert "memory" in section.lower(), (
        "the Lanes section does not say the judgment comes from the store "
        "rather than from memory — that is the rule, not an aside"
    )


def test_the_lanes_section_justifies_two_and_not_more():
    """Two is a decision with a reason, not a placeholder for 'some'."""
    section = _lanes()
    assert re.search(r"why two lanes,? and not (?:three|more)", section, re.I), (
        "the Lanes section has no 'why two and not three' argument; without it "
        "a later reader reads 2 as an arbitrary cap and raises it"
    )
    assert re.search(r"one validation[^.]{0,60}at a time", section, re.I), (
        "the Lanes section does not say only one validation runs at a time — "
        "that is why a third lane buys no throughput"
    )
    assert "p50 8-11" in section and "p50 21-36" in section, (
        "the Lanes section does not cite the measured worker waits the second "
        "lane covers (p50 8-11 min here, 21-36 min on a larger project)"
    )


def test_the_lanes_section_states_the_merge_order_rule_and_its_conflict_path():
    section = _lanes()
    assert "acceptance order, never dispatch order" in section, (
        "the merge-order rule is missing from the Lanes section; it is the one "
        "rule two lanes add to the merge"
    )
    assert re.search(r"cut from the run branch before[^.]{0,60}merge", section, re.I), (
        "the Lanes section does not say why the second merge can conflict at "
        "all — the branch was cut before the first merge landed"
    )
    for phrase in ("pm_retry", "evidence.files", "rebase onto", "second conflict"):
        assert phrase in section, (
            f"the Lanes section does not route the conflict through {phrase!r}; "
            "the path is US-PM-51-8's, reused rather than restated"
        )
    assert "--max" in section, (
        "the Lanes section does not say a conflict retry is outside `--max`"
    )


def test_the_lanes_section_states_the_dependency_barrier():
    section = _lanes()
    assert re.search(
        r"never dispatches a task whose dependency is still in flight", section, re.I
    ), "the Lanes section does not state the dependency barrier"
    assert re.search(r"lane B idles", section, re.I), (
        "the Lanes section does not say an empty compatible set is an answer "
        "rather than an error — lane B idles until lane A is accepted"
    )


def test_the_lanes_section_states_the_validator_exclusion():
    section = _lanes()
    assert "out of scope" in section, (
        "the Lanes section does not say the other lane's files are out of "
        "scope for a verdict"
    )
    assert re.search(r"retry, not a park", section, re.I), (
        "the Lanes section does not say a diff reaching into the other lane is "
        "a retry rather than a park"
    )


def test_the_lanes_section_states_the_single_lane_default():
    section = _lanes()
    assert "`--lanes 1`" in section, (
        "the Lanes section does not name `--lanes 1`, the default and the "
        "behaviour every existing run keeps"
    )
    assert re.search(r"defaults? (?:to )?1", section, re.I), (
        "the Lanes section does not say 1 is the default"
    )


def test_the_lanes_section_cross_references_instead_of_repeating():
    """The neighbouring sections own their arguments; Lanes points at them."""
    section = _lanes()
    for reference in ("*Isolation model*", "*The validator subagent*"):
        assert reference in section, (
            f"the Lanes section does not cross-reference {reference}; repeating "
            "its argument instead is how two copies start disagreeing"
        )
    assert '"verdict":' not in section, (
        "the Lanes section restates the validator's JSON shape, which belongs "
        "to *The validator subagent*"
    )


def test_sizes_and_numbers_has_a_two_lanes_row():
    """The table is the index of every number the skill's instructions lean on."""
    rows = [
        _norm(line)
        for line in design_section("## Sizes and numbers").splitlines()
        if line.startswith("|") and "lane" in line.lower()
    ]
    assert len(rows) == 1, (
        f"'Sizes and numbers' has {len(rows)} rows mentioning lanes, expected 1"
    )
    row = rows[0]
    assert "--lanes" in row and re.search(r"\b2\b", row), (
        f"the lanes row does not give the number or the flag: {row!r}"
    )
    assert re.search(r"one validation|throughput", row, re.I), (
        f"the lanes row gives a number with no reason: {row!r}"
    )


#: the lanes paragraph of ``skills.md``, clause by clause
SKILLS_DOC_LANE_CLAUSES = {
    "the flag, with its values": lambda s: "`--lanes <1|2>`" in s,
    "the default of one": lambda s: bool(re.search(r"default 1|keeps one task", s)),
    "lane B from the board filter": lambda s: "pm_board(lane_compatible_with=" in s,
    "one validation at a time": lambda s: bool(
        re.search(r"one validation at a time", s, re.I)
    ),
    "merge order": lambda s: "acceptance order, never dispatch order" in s,
    "the design doc under Lanes": lambda s: "under *Lanes*" in s,
}


@pytest.mark.parametrize("clause", list(SKILLS_DOC_LANE_CLAUSES))
def test_the_skills_catalogue_describes_the_lanes(clause):
    """A reader deciding whether to pass ``--lanes 2`` meets it here first."""
    section = _skills_orchestrate_section()
    assert SKILLS_DOC_LANE_CLAUSES[clause](section), (
        f"{SKILLS_DOC}'s /pm-orchestrate entry fails: {clause}"
    )


def test_the_skills_catalogue_no_longer_calls_the_loop_sequential():
    """A catalogue promising strictly sequential workers contradicts `--lanes 2`."""
    section = _skills_orchestrate_section()
    assert not re.search(r"run sequentially", section, re.I), (
        f"{SKILLS_DOC}'s /pm-orchestrate entry still says workers run "
        "sequentially, which `--lanes 2` makes false"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
