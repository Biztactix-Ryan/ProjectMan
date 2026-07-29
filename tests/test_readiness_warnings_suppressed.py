"""Always-on readiness warnings are gone from the payload (US-PM-4-6).

Closes two of US-PM-4's acceptance criteria:

* "Warnings that would fire on every item in a project are suppressed"
* "Payload size for pm_grab and pm_get drops measurably"

Background: ``readiness.py`` appended three warnings unconditionally — "no
Implementation section in description", "no Testing section in description",
"no Definition of Done checklist".  US-PM-4-5's determination
(``docs/reference/readiness-warnings-determination.md``) measured them at
**864 of 864 warning-bearing payloads carrying all three — 100.00%, zero
partials** — across a 3,527-call, four-project telemetry corpus, costing 131
bytes per affected call.  A signal present in every sample carries no
information.  The layout they demanded had no producer: ``create_task`` writes
the caller's description verbatim, and the only template defining it
(``templates/task.md.j2``) was unreferenced dead code, deleted with this
change.

Kept deliberately: the ``high points`` warning (genuinely conditional) and
every blocker (load-bearing — ``pm_grab``'s ``not_ready`` path depends on them).

Note on the criterion's wording — HALF OF IT IS UNMEETABLE (US-PM-4-3).
"Payload size for pm_grab and pm_get drops measurably" asserts a drop on two
surfaces, but ``pm_get`` never emitted these warnings, so there is no drop to
measure on it.  Only one expression in the whole package moves readiness
warnings into a payload, and it is in ``pm_grab``; ``pm_get`` never calls
``check_readiness`` on any path.  The corpus agrees (1 of 427 ``pm_get`` calls
contained the string — a nested quotation in a task body, not an emission).

So: the measurable drop is asserted on ``pm_grab`` (``TestPayloadSize``), and
the ``pm_get`` half is pinned instead as a regression guard on a cost that was
never paid (``TestPmGetNeverCarriedTheWarnings``) — it fails if anyone wires
readiness into ``pm_get`` and introduces the cost there.  The criterion text
needs a human decision to amend; no code change is implied.
"""

import ast
import inspect
from pathlib import Path

import pytest
import yaml


SUPPRESSED = (
    "no Implementation section in description",
    "no Testing section in description",
    "no Definition of Done checklist",
)

# A body in the prose form ProjectMan's scoper actually asks for: no headings,
# no checklist.  This is what real task bodies look like — 0 of 118 task files
# in ProjectMan's own .project/ contain any of the three demanded structures.
PROSE_BODY = (
    "Add the login endpoint to the API router: a POST /login handler that "
    "accepts email and password, validates credentials against the user "
    "store, and returns a signed JWT. Touches api/routes.py and auth/jwt.py."
)


@pytest.fixture(autouse=True)
def _clear_store_cache():
    from projectman.server import _store_cache

    _store_cache.clear()
    yield
    _store_cache.clear()


def _grab_payload(tmp_project, monkeypatch, body=PROSE_BODY, points=2, n=1):
    """Create ``n`` tasks the normal way and return the pm_grab payload of #1."""
    monkeypatch.chdir(tmp_project)
    from projectman.server import pm_create_story, pm_create_task, pm_grab, pm_update

    pm_create_story("Story", "A story description that is long enough.")
    pm_update("US-TST-1", status="active")
    for i in range(n):
        pm_create_task("US-TST-1", f"Task {i + 1}", body, points=points)
    return pm_grab("US-TST-1-1")


class TestWarningsSuppressed:
    def test_none_of_the_three_appear_in_a_grab_payload(
        self, tmp_project, monkeypatch
    ):
        payload = _grab_payload(tmp_project, monkeypatch)
        assert payload.startswith("grabbed:")
        for warning in SUPPRESSED:
            assert warning not in payload

    def test_no_warning_fires_on_every_item(self, tmp_project, monkeypatch):
        """AC1: no warning may have a 100% hit rate across a sample project.

        Creates a spread of tasks through the ordinary ``create_task`` path
        and asserts that no single warning string is present on all of them.
        This failed on all three deleted warnings before US-PM-4-6.
        """
        monkeypatch.chdir(tmp_project)
        from projectman.readiness import check_readiness
        from projectman.store import Store

        store = Store(tmp_project)
        store.create_story("Story", "A story description that is long enough.")
        store.update("US-TST-1", status="active")
        bodies = [
            PROSE_BODY,
            PROSE_BODY + "\n\n## Implementation\n\nUse the existing router.",
            "Short but sufficient prose describing a real unit of work here.",
            PROSE_BODY + "\n\n- [x] already finished this checklist item",
        ]
        for i, body in enumerate(bodies):
            store.create_task("US-TST-1", f"Task {i + 1}", body, points=2)

        per_task = []
        for i in range(len(bodies)):
            meta, body = store.get_task(f"US-TST-1-{i + 1}")
            per_task.append(set(check_readiness(meta, body, store)["warnings"]))

        assert per_task, "no tasks sampled"
        always_on = set.intersection(*per_task)
        assert always_on == set(), (
            f"warning(s) firing on 100% of items: {sorted(always_on)}"
        )

    def test_warnings_key_absent_not_empty(self, tmp_project, monkeypatch):
        """An empty ``warnings: []`` still costs bytes and reads as a signal."""
        payload = _grab_payload(tmp_project, monkeypatch)
        parsed = yaml.safe_load(payload)

        assert "warnings" not in parsed["grabbed"]
        assert parsed["grabbed"].get("warnings", "absent") != []
        assert "warnings" not in payload

    def test_high_points_warning_still_reaches_the_payload(
        self, tmp_project, monkeypatch
    ):
        """The key appears only when something genuinely applies."""
        payload = _grab_payload(tmp_project, monkeypatch, points=8)
        parsed = yaml.safe_load(payload)

        assert parsed["grabbed"]["warnings"] == [
            "high points (8) — consider decomposing"
        ]
        for warning in SUPPRESSED:
            assert warning not in payload

    def test_blockers_still_gate_the_grab(self, tmp_project, monkeypatch):
        """Hard gates are untouched — pm_grab still refuses an unready task."""
        monkeypatch.chdir(tmp_project)
        from projectman.server import (
            pm_create_story,
            pm_create_task,
            pm_grab,
            pm_update,
        )

        pm_create_story("Story", "A story description that is long enough.")
        pm_update("US-TST-1", status="active")
        pm_create_task("US-TST-1", "Task", PROSE_BODY)  # no points
        parsed = yaml.safe_load(pm_grab("US-TST-1-1"))

        assert parsed["status"] == "not_ready"
        assert any("no point estimate" in b for b in parsed["blockers"])


class TestPayloadSize:
    def test_grab_payload_shrinks_by_the_full_warnings_block(
        self, tmp_project, monkeypatch
    ):
        """AC3: a measurable drop, measured against the pre-fix payload.

        The reference is reconstructed rather than asserted as a magic number:
        the payload we now emit is re-dumped with the three warnings put back
        exactly as ``pm_grab`` used to emit them, and the delta is the real
        saving.  Measured at 131 bytes/call on all 81 grabbable tasks in
        ProjectMan's own .project/ — identical on every one.
        """
        payload = _grab_payload(tmp_project, monkeypatch)
        parsed = yaml.safe_load(payload)
        assert "warnings" not in parsed["grabbed"]

        old = {"grabbed": {**parsed["grabbed"], "warnings": list(SUPPRESSED)}}
        old_payload = yaml.dump(old, default_flow_style=False, sort_keys=False)

        saved = len(old_payload.encode()) - len(payload.encode())
        assert saved == 131, f"expected a 131-byte drop, measured {saved}"
        assert len(payload.encode()) < len(old_payload.encode())

    def test_empty_list_would_still_have_cost_bytes(self, tmp_project, monkeypatch):
        """Omitting the key beats emitting ``warnings: []``."""
        payload = _grab_payload(tmp_project, monkeypatch)
        parsed = yaml.safe_load(payload)

        empty = {"grabbed": {**parsed["grabbed"], "warnings": []}}
        empty_payload = yaml.dump(empty, default_flow_style=False, sort_keys=False)

        assert len(payload.encode()) < len(empty_payload.encode())

    def test_saving_holds_for_every_grabbable_item_in_varied_states(
        self, tmp_project, monkeypatch
    ):
        """The drop is a property of the payload, not of one lucky task.

        The two tests above measure a single prose task.  That leaves the
        criterion's word "measurably" resting on one sample, and it cannot
        distinguish "the warnings block is gone" from "this particular body
        happened not to trigger it".  Here the same reconstruction runs over
        every grabbable item in ``VARIED_ITEMS`` — bodies from empty to fully
        structured, points either side of the decompose threshold — and the
        saving is asserted to be uniform and strictly positive on all of them.

        Two exact values are expected, and the difference between them is
        itself meaningful:

        * **131 bytes** when the task has no surviving warning.  The whole
          block goes: the ``  warnings:\\n`` key line (12 bytes) plus three
          ``  - <text>\\n`` list entries (119 bytes).
        * **119 bytes** when a genuine warning (``high points``) still
          occupies the key.  Only the three list entries go; the key line is
          still earned, so it stays.

        Byte counts are order-independent here — the block is a flat YAML list
        of the same three strings however they were originally sequenced.
        """
        monkeypatch.chdir(tmp_project)
        from projectman.server import _store_cache, pm_grab

        _store_cache.clear()
        _build_project(tmp_project, VARIED_ITEMS)
        _store_cache.clear()

        no_key, had_key, proportions = [], [], []
        for i in range(len(VARIED_ITEMS)):
            payload = pm_grab(f"US-TST-1-{i + 1}")
            parsed = yaml.safe_load(payload)
            if "grabbed" not in parsed:
                continue  # not_ready — blockers, no payload to measure

            surviving = parsed["grabbed"].get("warnings")
            for suppressed in SUPPRESSED:
                assert suppressed not in payload

            # Rebuild the pre-fix payload: the three deleted warnings put back
            # ahead of whatever genuinely still applies.
            old = {
                "grabbed": {
                    **parsed["grabbed"],
                    "warnings": list(SUPPRESSED) + (surviving or []),
                }
            }
            old_payload = yaml.dump(old, default_flow_style=False, sort_keys=False)

            saved = len(old_payload.encode()) - len(payload.encode())
            assert saved > 0, f"US-TST-1-{i + 1} saved nothing"
            (had_key if surviving else no_key).append(saved)
            proportions.append(saved / len(old_payload.encode()))

        assert no_key, "no item exercised the whole-block saving"
        assert had_key, "no item exercised the key-retained saving"
        assert set(no_key) == {131}, f"non-uniform whole-block saving: {set(no_key)}"
        assert set(had_key) == {119}, f"non-uniform list-only saving: {set(had_key)}"

        # Expressed as a proportion: a drop that survives being normalised by
        # payload size is a real saving rather than a rounding artefact.
        assert min(proportions) > 0.03, (
            "the saving is under 3% of the pre-fix payload on some item — "
            f"proportions={[round(p, 4) for p in proportions]}"
        )


def test_dead_task_template_is_gone():
    """``templates/task.md.j2`` defined the demanded layout and was never loaded.

    It is deleted so the check cannot be resurrected by pointing at it.
    """
    from pathlib import Path

    import projectman

    templates = Path(projectman.__file__).parent / "templates"
    assert templates.is_dir()
    assert not (templates / "task.md.j2").exists()


def test_readiness_source_has_no_body_structure_checks():
    """Guard against reintroduction in ``check_readiness``."""
    import inspect

    from projectman import readiness

    source = inspect.getsource(readiness.check_readiness)
    for warning in SUPPRESSED:
        assert warning not in source


# ─── US-PM-4-1: the standing guard ───────────────────────────────────
#
# The acceptance criterion is a *general property*, not a claim about three
# particular strings: "warnings that would fire on every item in a project are
# suppressed".  Asserting only that the three deleted strings are gone makes
# this a one-time cleanup; the next contributor who adds an unconditional
# `warnings.append(...)` reintroduces exactly the defect US-PM-4 was raised to
# fix and every test above still passes.
#
# So the guard below never names a warning.  It derives the warning universe
# from what the code actually emits over a varied sample project, computes a
# hit rate for each, and fails if any warning reaches 100%.  A second, static
# pass reads `check_readiness`'s own AST and fails on any `warnings.append`
# that no branch guards — that one catches an always-on warning even if the
# sample happened not to exercise it.


BODIES = {
    "prose": PROSE_BODY,
    "prose_long": (
        "Rework the sprint burndown so archived stories stop skewing the "
        "remaining-points line. The chart currently sums every story attached "
        "to the sprint; archived work should be excluded from the denominator "
        "but still shown as a separate completed band. Touches metrics.py and "
        "the burndown serializer."
    ),
    "completed_dod": (
        "Ship the login endpoint and verify it end to end.\n\n"
        "Definition of done:\n\n- [x] Endpoint works\n- [x] Tests pass\n"
    ),
    "thin": "Do the thing.",
    "empty": "",
    # Structured bodies.  Deliberately kept OUT of the hit-rate sample below —
    # see the note on REALISTIC_ITEMS.
    "impl_section": PROSE_BODY + "\n\n## Implementation\n\nUse the existing router.",
    "full_structure": (
        "## Implementation\n\nAdd the handler.\n\n"
        "## Testing\n\nRun pytest tests/test_auth.py.\n\n"
        "## Definition of Done\n\n- [ ] Endpoint works\n- [ ] Tests pass\n"
    ),
}

# (body key, points, status, assignee).
#
# The hit-rate sample.  Every body here is one a ProjectMan generator actually
# produces: `create_task` writes the caller's description verbatim and the
# scoper asks for prose, so 0 of the 118 task files in ProjectMan's own
# .project/ contain a `## Implementation` heading, a `## Testing` heading, or
# an open `- [ ]` checklist.  Hand-writing such a body into this sample would
# make a useless always-on warning *look* conditional and quietly defeat the
# guard — that is exactly the vacuous version of this test, so the structured
# bodies live in VARIED_ITEMS instead and are asserted against separately.
#
# Points straddle the decompose threshold (>5) in both directions, and
# statuses/assignees vary, so the surviving warning is observed as genuinely
# conditional rather than merely absent.
REALISTIC_ITEMS = [
    ("prose", 1, None, None),
    ("prose", 2, None, None),
    ("prose_long", 3, None, None),
    ("prose", 5, None, None),
    ("completed_dod", 3, None, None),
    ("prose", 8, None, None),
    ("prose_long", 13, None, None),
    ("completed_dod", 8, None, None),
    ("thin", 2, None, None),
    ("empty", 2, None, None),
    ("prose", None, None, None),
    ("prose", 2, None, "alice"),
    ("prose_long", 5, "in-progress", "bob"),
    ("prose", 2, "done", "bob"),
]

# The realistic sample plus the two structured layouts, for asserting the
# three specific warnings are gone whatever shape the body takes.
VARIED_ITEMS = REALISTIC_ITEMS + [
    ("impl_section", 3, None, None),
    ("full_structure", 5, None, None),
    ("full_structure", 13, None, None),
]


def _build_project(tmp_project, items):
    """Build a multi-item project and return (store, [task_ids])."""
    from projectman.store import Store, _cache

    _cache.clear()
    store = Store(tmp_project)
    store.create_story("Story", "A story description that is long enough.")
    store.update("US-TST-1", status="active")

    ids = []
    for i, (body_key, points, status, assignee) in enumerate(items):
        task_id = f"US-TST-1-{i + 1}"
        store.create_task("US-TST-1", f"Task {i + 1}", BODIES[body_key], points=points)
        if assignee:
            store.update(task_id, assignee=assignee)
        if status:
            store.update(task_id, status=status)
        ids.append(task_id)
    return store, ids


def _warning_sets(store, ids):
    """The set of warnings ``check_readiness`` emits for each sampled item."""
    from projectman.readiness import check_readiness

    out = []
    for task_id in ids:
        meta, body = store.get_task(task_id)
        out.append(set(check_readiness(meta, body, store)["warnings"]))
    return out


def _hit_rates(warning_sets):
    """{warning: fraction of items it fired on} over the observed universe."""
    universe = set().union(*warning_sets) if warning_sets else set()
    total = len(warning_sets)
    return {w: sum(w in s for s in warning_sets) / total for w in universe}


def _is_warnings_mutation(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("append", "extend")
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "warnings"
    )


def _scan_block(stmts, guarded, offenders):
    """Collect ``warnings.append`` calls that no branch guards."""
    for stmt in stmts:
        if isinstance(stmt, ast.Expr) and _is_warnings_mutation(stmt.value):
            if not guarded:
                offenders.append(ast.unparse(stmt.value))
            continue
        if isinstance(stmt, ast.If):
            _scan_block(stmt.body, True, offenders)
            _scan_block(stmt.orelse, True, offenders)
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            _scan_block(stmt.body, True, offenders)
            _scan_block(stmt.orelse, True, offenders)
        elif isinstance(stmt, ast.Try):
            # A ``try`` body runs unconditionally; only handlers are guarded.
            _scan_block(stmt.body, guarded, offenders)
            for handler in stmt.handlers:
                _scan_block(handler.body, True, offenders)
            _scan_block(stmt.orelse, guarded, offenders)
            _scan_block(stmt.finalbody, guarded, offenders)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            _scan_block(stmt.body, guarded, offenders)
        elif isinstance(stmt, ast.Match):
            for case in stmt.cases:
                _scan_block(case.body, True, offenders)


class TestNoWarningFiresOnEveryItem:
    """AC: warnings that would fire on every item are suppressed."""

    def test_no_warning_has_a_100_percent_hit_rate(self, tmp_project):
        """The property, over the whole warning universe the code emits.

        Nothing here is hardcoded to the three deleted strings: whatever
        ``check_readiness`` emits is measured, so a future unconditional
        warning fails this test the day it is added.
        """
        store, ids = _build_project(tmp_project, REALISTIC_ITEMS)
        rates = _hit_rates(_warning_sets(store, ids))

        always_on = {w: r for w, r in rates.items() if r == 1.0}
        assert always_on == {}, (
            f"warning(s) firing on 100% of {len(ids)} items — zero information, "
            f"pure payload cost: {sorted(always_on)}"
        )

    def test_the_sample_is_not_vacuous(self, tmp_project):
        """Anti-vacuity: "no warning is always-on" must not pass by silence.

        If ``check_readiness`` simply stopped emitting warnings the assertion
        above would pass trivially.  Require the sample to actually observe a
        warning, and to observe it as *conditional* — fired on some items and
        not others — which is the only shape a useful warning has.
        """
        store, ids = _build_project(tmp_project, REALISTIC_ITEMS)
        warning_sets = _warning_sets(store, ids)
        rates = _hit_rates(warning_sets)

        assert rates, "no warning was observed at all — the guard would be vacuous"
        conditional = {w: r for w, r in rates.items() if 0.0 < r < 1.0}
        assert conditional, f"no warning fired conditionally; rates={rates}"

    def test_blockers_still_fire_and_are_still_conditional(self, tmp_project):
        """Anti-vacuity for the hard gates: suppression touched none of them."""
        from projectman.readiness import check_readiness

        store, ids = _build_project(tmp_project, REALISTIC_ITEMS)
        results = []
        for task_id in ids:
            meta, body = store.get_task(task_id)
            results.append(check_readiness(meta, body, store))

        blocked = [r for r in results if r["blockers"]]
        assert blocked, "no item was blocked — blockers are no longer load-bearing"
        assert [r for r in results if r["ready"]], "no item was ready"

        blocker_sets = [set(r["blockers"]) for r in results]
        assert set.intersection(*blocker_sets) == set(), (
            "a blocker fires on every item — same defect, different key"
        )

    def test_every_warning_append_is_guarded_by_a_condition(self):
        """Static counterpart: read the code, not just its output.

        An ``warnings.append(...)`` sitting at the top level of the function
        body is unconditional *by construction* — it cannot have a hit rate
        below 100%.  This catches the reintroduction even in a build where the
        sample project above fails to exercise it.  Every function in
        ``readiness`` that touches a local ``warnings`` list is scanned, so
        moving the code into a helper does not evade the guard.
        """
        from projectman import readiness

        module = ast.parse(inspect.getsource(readiness))
        scanned = []
        offenders = []
        for node in ast.walk(module):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(
                    _is_warnings_mutation(n) for n in ast.walk(node)
                ):
                    scanned.append(node.name)
                    _scan_block(node.body, False, offenders)

        assert scanned, "found no warning-emitting function to scan — guard is dead"
        assert offenders == [], (
            "unconditional warning(s) in readiness — these fire on every item "
            f"and must not ship: {offenders}"
        )


class TestSuppressedAcrossVariedItemStates:
    """AC: the three specific always-on warnings are gone from every surface."""

    def test_absent_for_every_item_state(self, tmp_project):
        """No body, prose, sections, completed DoD, points either side of 5."""
        store, ids = _build_project(tmp_project, VARIED_ITEMS)
        for task_id, warnings in zip(ids, _warning_sets(store, ids)):
            for suppressed in SUPPRESSED:
                assert suppressed not in warnings, f"{suppressed!r} on {task_id}"

    def test_absent_from_grab_and_get_payloads(self, tmp_project, monkeypatch):
        """The two payload surfaces the criterion names, over the same sample."""
        monkeypatch.chdir(tmp_project)
        _build_project(tmp_project, VARIED_ITEMS)
        from projectman.server import _store_cache, pm_get, pm_grab

        _store_cache.clear()
        payloads = [pm_get(f"US-TST-1-{i + 1}") for i in range(len(VARIED_ITEMS))]
        for i in range(len(VARIED_ITEMS)):
            payloads.append(pm_grab(f"US-TST-1-{i + 1}"))

        blob = "\n".join(payloads)
        for suppressed in SUPPRESSED:
            assert suppressed not in blob

    def test_absent_from_the_board(self, tmp_project, monkeypatch):
        """``pm_board`` runs readiness over every todo task."""
        monkeypatch.chdir(tmp_project)
        _build_project(tmp_project, VARIED_ITEMS)
        from projectman.server import _store_cache, pm_board

        _store_cache.clear()
        payload = pm_board()
        for suppressed in SUPPRESSED:
            assert suppressed not in payload

    def test_no_shipped_string_literal_contains_them(self):
        """Gone from the source of every surface, not just from readiness.py.

        String literals only — the explanatory comment in ``readiness.py``
        naming the deleted checks is documentation, not a payload, and does
        not appear in the AST.
        """
        import projectman

        src = Path(projectman.__file__).parent
        found = []
        for path in sorted(src.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for suppressed in SUPPRESSED:
                        if suppressed in node.value:
                            found.append(f"{path}: {suppressed!r}")
        assert found == [], f"suppressed warning text still in source: {found}"

    def test_warnings_key_tracks_whether_anything_applies(
        self, tmp_project, monkeypatch
    ):
        """Absent when there is nothing to say, present when there is.

        Asserted across the sample rather than on a single task, so this also
        shows the *key itself* is not a 100%-hit-rate signal.
        """
        monkeypatch.chdir(tmp_project)
        _build_project(tmp_project, VARIED_ITEMS)
        from projectman.server import _store_cache, pm_grab

        _store_cache.clear()
        with_key, without_key = 0, 0
        for i in range(len(VARIED_ITEMS)):
            parsed = yaml.safe_load(pm_grab(f"US-TST-1-{i + 1}"))
            if "grabbed" not in parsed:
                continue  # not_ready — blockers, no payload
            if "warnings" in parsed["grabbed"]:
                assert parsed["grabbed"]["warnings"], "warnings key present but empty"
                with_key += 1
            else:
                without_key += 1

        assert with_key, "the warnings key never appeared — it would be dead weight"
        assert without_key, "the warnings key appeared on every payload"


# ─── US-PM-4-3: the pm_get half of the criterion ─────────────────────
#
# The acceptance criterion reads "Payload size for pm_grab and pm_get drops
# measurably".  The pm_grab half is proven above.  The pm_get half is
# UNMEETABLE AS WRITTEN, and the tests below say so honestly rather than
# faking a measurement.
#
# pm_get never carried these warnings, so there is no drop to measure on it.
# Three independent verifications, each capable of falsifying the others:
#
#   1. Static, by emission site.  Exactly one expression in the entire
#      package moves readiness warnings into a payload —
#      `server.py: grabbed["warnings"] = readiness["warnings"]`, inside
#      pm_grab.  Not the web API's grab_task, not pm_board (both consume only
#      `ready` and `blockers`), and not pm_get.
#   2. Static, by reachability.  A deliberately OVER-approximating call-graph
#      closure from pm_get — resolving calls by bare name across the whole
#      package, ignoring the receiver, so it credits far more edges than can
#      really exist — still never reaches check_readiness.
#   3. Runtime.  Calling pm_get over a varied project with check_readiness
#      instrumented records zero invocations.
#
# Measured against ProjectMan's own .project/: pm_get over all 136 real items
# invoked check_readiness 0 times.  One of those 136 payloads did contain a
# suppressed warning string — it is the US-PM-4 story body quoting the
# warnings it was raised to delete, i.e. prose in a `body` field, never a
# `warnings` key.  That matches the telemetry corpus exactly (1 of 427 pm_get
# calls, a nested quotation).
#
# So the useful assertion is not "pm_get got smaller" but "pm_get never
# carried these warnings, and still does not".  That is a regression guard
# with real teeth: it fails the day someone wires readiness into pm_get and
# reintroduces the per-call cost on a 427-call-per-corpus read surface.
#
# ACTION REQUIRED BY A HUMAN: the criterion text should be amended to name
# only pm_grab (or to say "the surfaces that carried them").  Nothing in the
# code needs to change.


def _package_function_defs():
    """{bare name: [FunctionDef]} for every function in the projectman package."""
    import collections

    import projectman

    defs = collections.defaultdict(list)
    src = Path(projectman.__file__).parent
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs[node.name].append(node)
    return defs


def _referenced_names(node):
    """Every identifier referenced in a function body, receiver ignored.

    ``store.get_task(...)`` contributes ``get_task``; a bare reference to a
    function passed as a value contributes its name too.  Discarding the
    receiver is intentional: it makes the resulting graph an over-approxima-
    tion, so "unreachable" is a strong claim rather than a lucky one.
    """
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _reachable_from(entry, defs):
    """Transitive closure of names reachable from ``entry``."""
    import collections

    seen, queue = set(), collections.deque([entry])
    while queue:
        name = queue.popleft()
        if name in seen:
            continue
        seen.add(name)
        for node in defs.get(name, []):
            for called in _referenced_names(node):
                if called in defs and called not in seen:
                    queue.append(called)
    return seen


class TestPmGetNeverCarriedTheWarnings:
    """AC (pm_get half): unmeetable — that surface never carried the bytes.

    Read these as a regression guard on a *cost that was never paid*, not as
    a measured saving.  See the block comment above for why the criterion
    cannot be met as written and what a human needs to decide.
    """

    def test_pm_grab_is_the_only_payload_emission_site_in_the_package(self):
        """Pins the emission surface at exactly one function.

        If a second surface ever starts putting ``readiness["warnings"]`` into
        a response, this fails and names it — which is the event that would
        make the pm_get half of the criterion meetable after all.
        """
        import projectman

        emitters = []
        src = Path(projectman.__file__).parent
        for path in sorted(src.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Subscript)
                        and isinstance(sub.slice, ast.Constant)
                        and sub.slice.value == "warnings"
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "readiness"
                        and isinstance(sub.ctx, ast.Load)
                    ):
                        emitters.append(node.name)
                        break

        assert sorted(set(emitters)) == ["pm_grab"], (
            "the set of functions reading readiness['warnings'] changed; "
            f"expected only pm_grab, found {sorted(set(emitters))}"
        )

    def test_no_call_path_from_pm_get_reaches_check_readiness(self):
        """Static reachability, over-approximated so a miss is meaningful."""
        defs = _package_function_defs()
        assert "pm_get" in defs, "pm_get not found — guard is dead"

        reachable = _reachable_from("pm_get", defs)
        assert "check_readiness" not in reachable, (
            "pm_get can now reach check_readiness — if it also emits the "
            "warnings, the US-PM-4 payload-size criterion becomes meetable on "
            "pm_get and this guard should be replaced by a real measurement"
        )

        # Anti-vacuity: the same closure must find the path that does exist,
        # otherwise a broken traversal would silently "prove" anything.
        assert "check_readiness" in _reachable_from("pm_grab", defs), (
            "the closure failed to find pm_grab -> check_readiness, so its "
            "negative result for pm_get proves nothing"
        )

    def test_pm_get_does_not_invoke_readiness_at_runtime(
        self, tmp_project, monkeypatch
    ):
        """Runtime counterpart: instrument check_readiness and count calls.

        ``pm_grab`` imports it inside the function body, so patching the
        module attribute is picked up at call time — meaning this catches a
        future pm_get that starts calling it, however it imports it.
        """
        monkeypatch.chdir(tmp_project)
        _build_project(tmp_project, VARIED_ITEMS)

        from projectman import readiness
        from projectman.server import _store_cache, pm_get, pm_grab

        _store_cache.clear()
        calls = []
        original = readiness.check_readiness

        def counting(meta, body, store):
            calls.append(meta.id)
            return original(meta, body, store)

        monkeypatch.setattr(readiness, "check_readiness", counting)

        for i in range(len(VARIED_ITEMS)):
            pm_get(f"US-TST-1-{i + 1}")
        pm_get("US-TST-1")

        assert calls == [], (
            f"pm_get invoked check_readiness on {calls} — it never used to; "
            "the warnings cost may have been reintroduced on a read surface"
        )

        # Anti-vacuity: the instrument works.  pm_grab must trip it.
        pm_grab("US-TST-1-1")
        assert calls, "the instrumented check_readiness was never called at all"

    def test_pm_get_payload_carries_no_warnings_key_for_any_item(
        self, tmp_project, monkeypatch
    ):
        """The payload-shape guard, over every item state and every item type.

        Deliberately asserts on the parsed *key*, not on a substring search.
        "The warning strings are absent from the text" is the weak assertion
        that would pass for the wrong reason — a task body legitimately
        quoting a warning (as US-PM-4's own story body does) contains the
        string while emitting nothing.  What matters is that pm_get has no
        ``warnings`` key to carry a readiness block in.
        """
        monkeypatch.chdir(tmp_project)
        _build_project(tmp_project, VARIED_ITEMS)
        from projectman.server import _store_cache, pm_get

        _store_cache.clear()
        ids = [f"US-TST-1-{i + 1}" for i in range(len(VARIED_ITEMS))] + ["US-TST-1"]
        for item_id in ids:
            parsed = yaml.safe_load(pm_get(item_id))
            assert "warnings" not in parsed, (
                f"pm_get({item_id}) now returns a warnings key — the surface "
                "that never carried readiness warnings has started to"
            )

    def test_a_quoted_warning_in_a_body_is_not_an_emission(
        self, tmp_project, monkeypatch
    ):
        """Why the substring test would have been the wrong assertion.

        Reproduces the single corpus false positive: a task whose *body*
        quotes the deleted warnings, exactly as US-PM-4's story body does.
        The string is present in the payload and no warning was emitted.  A
        test asserting "pm_get payloads do not contain the warning strings"
        fails here while the code is entirely correct — which is precisely
        why this criterion is pinned on the key, not on the text.
        """
        monkeypatch.chdir(tmp_project)
        from projectman.server import (
            _store_cache,
            pm_create_story,
            pm_create_task,
            pm_get,
            pm_update,
        )

        _store_cache.clear()
        quoting_body = (
            "Delete the always-on readiness warnings. readiness.py appends "
            "three unconditionally: " + ", ".join(SUPPRESSED) + ". They fire "
            "on every item, so they carry no information."
        )
        pm_create_story("Story", "A story description that is long enough.")
        pm_update("US-TST-1", status="active")
        pm_create_task("US-TST-1", "Task", quoting_body, points=2)

        payload = pm_get("US-TST-1-1")
        parsed = yaml.safe_load(payload)

        # The strings are present in the payload the caller receives...
        #
        # Searched against whitespace-normalised text because YAML line-wraps
        # long scalars, so the raw dump splits these strings across lines.
        # That is a second, independent reason the naive "the warning text is
        # absent from the payload" assertion is unfit: it can pass simply
        # because the dumper broke the string, with nothing suppressed at all.
        flat = " ".join(payload.split())
        for suppressed in SUPPRESSED:
            assert suppressed in flat

        # ...purely as body prose.  Nothing was emitted.
        assert "warnings" not in parsed
        for suppressed in SUPPRESSED:
            assert suppressed in parsed["body"]
