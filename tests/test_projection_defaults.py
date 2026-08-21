"""The *default* shape of the four projectable read tools (US-PM-10-4).

US-PM-10 added `fields` to `pm_get`/`pm_grab` (US-PM-10-6) and `brief`/`fields`
to `pm_batch_get`/`pm_list_sprints` (US-PM-10-7).  Its acceptance criterion —
*default behaviour is unchanged when no projection is requested* — is the one
that cannot be proved by the tests that ship with those tasks.

``tests/test_field_projection.py`` and ``tests/test_brief_mode.py`` already pin
the *within-version* half: `test_pm_get_default_is_byte_identical_*`,
`test_pm_get_multi_id_default_is_byte_identical`,
`test_pm_get_default_with_include_log_is_byte_identical`,
`test_pm_grab_default_is_byte_identical` and the brief-mode default tests all
assert `f(x, fields=None) == f(x)`.  That is necessary and not sufficient: both
sides of those equalities move together, so a regression that changed the
default output would keep every one of them green.

This file pins the *absolute* shape instead.  A deterministic fixture project
is built, the four tools are called with no projection arguments, and the
responses are compared byte-for-byte against golden files in
``tests/golden/projection_defaults/``.  Those goldens were generated from the
post-sprint code and verified equal to the pre-sprint code (commit 9f39102) by
a one-off control run against a `git worktree` of HEAD, over this same fixture.
The single legitimate difference found there is the `has_evidence` marker that
US-PM-9-7 adds to `pm_get(include_log=True)` entries (evidence contract §4);
it is baked into ``pm_get_task_include_log.yaml`` on purpose.

Two structural pins go with the goldens: the projection parameters must stay
*trailing* and optional, so no future reorder can silently shift a positional
caller onto them; and passing them explicitly at their defaults must equal
omitting them.

To regenerate the goldens after an *intended* contract change::

    PM_UPDATE_GOLDEN=1 uv run --extra dev --with "mcp[cli]<2" \\
        python -m pytest tests/test_projection_defaults.py

and read the resulting diff as the change to the default read contract.
"""

import inspect
import os
import re
from pathlib import Path

import pytest
import yaml

GOLDEN_DIR = Path(__file__).parent / "golden" / "projection_defaults"

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


# ═══ Deterministic fixture ══════════════════════════════════════

# `created`/`updated` are today's date and run-log timestamps are the wall
# clock, so they cannot be golden-compared as they stand.  They are normalised
# rather than frozen: the alternative is monkeypatching `date`/`datetime` in
# `store`, which pins an implementation detail of *how* the store reads the
# clock instead of the response contract this file is about.  Actor comes from
# git config, so it is machine-dependent for the same reason.
_NORMALISERS = (
    (re.compile(r"^(\s*-?\s*(?:created|updated):\s*)'\d{4}-\d{2}-\d{2}'$", re.M), r"\1<DATE>"),
    (re.compile(r"^(\s*-?\s*timestamp:\s*)'[^']*'$", re.M), r"\1<TIMESTAMP>"),
    (re.compile(r"^(\s*-?\s*actor:\s*).*$", re.M), r"\1<ACTOR>"),
)


def _normalise(text: str) -> str:
    for pattern, repl in _NORMALISERS:
        text = pattern.sub(repl, text)
    return text


def _build(root: Path):
    """One epic, three stories with criteria, seven tasks, two sprints.

    Deliberately varied: every task status the projection could shape, one
    task carrying a run log, and one still-todo task with a ready body for
    `pm_grab` to claim.
    """
    from projectman.store import Store

    proj = root / ".project"
    proj.mkdir(parents=True)
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "config.yaml").write_text(
        yaml.dump(
            {
                "name": "test-project",
                "prefix": "TST",
                "description": "A test project",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            }
        )
    )
    (proj / "PROJECT.md").write_text("# test-project\n\nA test project.\n")

    s = Store(root)
    s.create_epic("Platform Epic", "Epic body text that is long enough to matter.")
    s.create_story(
        "First Story",
        "First story body, long enough to matter.",
        points=3,
        tags=["backend"],
        acceptance_criteria=["Users can log in", "Errors are surfaced"],
    )
    s.create_story(
        "Second Story",
        "Second story body, long enough to matter.",
        points=5,
        acceptance_criteria=["Data is persisted"],
    )
    s.create_story("Third Story", "Third story body, long enough to matter.", points=2)
    s.update("US-TST-1", status="active", epic_id="EPIC-TST-1")
    s.update("US-TST-2", status="ready", epic_id="EPIC-TST-1")
    s.update("US-TST-3", status="active", epic_id="EPIC-TST-1")

    s.create_task("US-TST-1", "Implement login", READY_BODY, points=2, tags=["auth"])
    s.create_task("US-TST-2", "Wire persistence", READY_BODY, points=1)
    s.create_task("US-TST-3", "Refactor module", READY_BODY, points=1)
    s.create_task("US-TST-3", "Grabbable task", READY_BODY, points=1)

    s.update("US-TST-1-1", status="done", assignee="alice")
    s.update("US-TST-1-2", status="blocked")
    s.update("US-TST-1-3", status="in-progress", assignee="bob")
    s.update("US-TST-2-1", status="review")
    s.update("US-TST-2-2", status="done", assignee="alice")
    # US-TST-3-1 and US-TST-3-2 stay todo; US-TST-3-2 is the grab target.
    s._append_run_log(
        "US-TST-1-1", "success", "Implemented and verified the login flow.", status="done"
    )
    s._append_run_log(
        "US-TST-1-1", "info", "Follow-up note about the login flow.", status="done"
    )

    s.create_sprint(
        "Sprint One",
        goal="Ship the login flow end to end.",
        start_date="2026-01-01",
        end_date="2026-01-14",
        planned_stories=["US-TST-1"],
    )
    s.create_sprint(
        "Sprint Two",
        goal="Persist the data and clean up.",
        start_date="2026-01-15",
        end_date="2026-01-28",
        planned_stories=["US-TST-2", "US-TST-3"],
    )
    s.update_sprint("SPRINT-TST-1", status="completed")
    s.update_sprint("SPRINT-TST-2", status="active")


@pytest.fixture
def project(tmp_path, monkeypatch):
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()
    _build(tmp_path)
    monkeypatch.chdir(tmp_path)
    clear_all_caches()
    _store_cache.clear()
    yield tmp_path
    clear_all_caches()
    _store_cache.clear()


def _assert_golden(name: str, text: str):
    path = GOLDEN_DIR / f"{name}.yaml"
    actual = _normalise(text)
    if os.environ.get("PM_UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual)
        return
    assert path.exists(), (
        f"missing golden {path} — regenerate with PM_UPDATE_GOLDEN=1"
    )
    assert actual == path.read_text(), (
        f"{name}: the no-projection response changed.  If that is intended, "
        f"regenerate with PM_UPDATE_GOLDEN=1 and review the diff as a change "
        f"to the default read contract."
    )


# ═══ Golden defaults: pm_get ════════════════════════════════════


def test_pm_get_epic_default_matches_golden(project):
    from projectman.server import pm_get

    _assert_golden("pm_get_epic", pm_get("EPIC-TST-1"))


def test_pm_get_story_default_matches_golden(project):
    from projectman.server import pm_get

    _assert_golden("pm_get_story", pm_get("US-TST-1"))


def test_pm_get_task_default_matches_golden(project):
    from projectman.server import pm_get

    _assert_golden("pm_get_task", pm_get("US-TST-1-3"))


def test_pm_get_multi_id_default_matches_golden(project):
    from projectman.server import pm_get

    _assert_golden("pm_get_multi", pm_get("US-TST-1,US-TST-2,US-TST-1-1"))


def test_pm_get_include_log_default_matches_golden(project):
    """`has_evidence` here is US-PM-9-7's marker, not a projection change."""
    from projectman.server import pm_get

    text = pm_get("US-TST-1-1", include_log=True)
    assert "recent_run_log" in text
    _assert_golden("pm_get_task_include_log", text)


# ═══ Golden defaults: pm_batch_get ══════════════════════════════


@pytest.mark.parametrize("kind", ["epics", "stories", "tasks"])
def test_pm_batch_get_by_type_default_matches_golden(project, kind):
    from projectman.server import pm_batch_get

    _assert_golden(f"pm_batch_get_{kind}", pm_batch_get(type=kind))


def test_pm_batch_get_by_ids_default_matches_golden(project):
    from projectman.server import pm_batch_get

    _assert_golden(
        "pm_batch_get_ids", pm_batch_get(ids="US-TST-1,US-TST-1-1,EPIC-TST-1")
    )


# ═══ Golden defaults: pm_list_sprints ═══════════════════════════


def test_pm_list_sprints_default_matches_golden(project):
    from projectman.server import pm_list_sprints

    _assert_golden("pm_list_sprints", pm_list_sprints())


def test_pm_list_sprints_filtered_default_matches_golden(project):
    from projectman.server import pm_list_sprints

    _assert_golden(
        "pm_list_sprints_completed", pm_list_sprints(status="completed")
    )


# ═══ Golden defaults: pm_grab ═══════════════════════════════════


def test_pm_grab_default_matches_golden(project):
    from projectman.server import pm_grab

    _assert_golden("pm_grab", pm_grab("US-TST-3-2"))


# ═══ Explicit defaults equal omitted ════════════════════════════


def test_pm_get_explicit_fields_none_equals_omitted(project):
    from projectman.server import pm_get

    assert pm_get("US-TST-1-3", fields=None) == pm_get("US-TST-1-3")
    assert pm_get("US-TST-1-1", include_log=True, fields=None) == pm_get(
        "US-TST-1-1", include_log=True
    )


def test_pm_batch_get_explicit_defaults_equal_omitted(project):
    from projectman.server import pm_batch_get

    for kind in ("epics", "stories", "tasks"):
        assert pm_batch_get(type=kind, brief=False, fields=None) == pm_batch_get(
            type=kind
        )
    assert pm_batch_get(ids="US-TST-1", brief=False, fields=None) == pm_batch_get(
        ids="US-TST-1"
    )


def test_pm_list_sprints_explicit_defaults_equal_omitted(project):
    from projectman.server import pm_list_sprints

    assert pm_list_sprints(brief=False, fields=None) == pm_list_sprints()
    assert pm_list_sprints(
        status="completed", brief=False, fields=None
    ) == pm_list_sprints(status="completed")


def test_pm_grab_explicit_fields_none_equals_omitted(project):
    """Re-claiming by the same assignee is idempotent, so both calls are equal."""
    from projectman.server import pm_grab

    assert pm_grab("US-TST-3-2") == pm_grab("US-TST-3-2", fields=None)


# ═══ Signatures: projection stays trailing and optional ═════════

# The full parameter order, pinned.  A positional caller of any of these tools
# — `pm_get(task_id, True)` — lands on a *different* parameter the moment
# somebody inserts `fields` earlier in the list, and nothing else in the suite
# would notice.  The projection parameters are named separately so the test
# can assert they are the trailing ones.
EXPECTED_SIGNATURES = {
    "pm_get": (("id", "include_log", "project", "task_id"), ("fields",)),
    "pm_batch_get": (("type", "ids", "project"), ("brief", "fields")),
    "pm_grab": (
        ("task_id", "assignee", "include_story", "project", "id"),
        ("fields",),
    ),
    "pm_list_sprints": (("status", "project"), ("brief", "fields")),
}

PROJECTION_DEFAULTS = {"fields": None, "brief": False}


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_SIGNATURES))
def test_projection_params_are_trailing_and_optional(tool_name):
    import projectman.server as server

    leading, projection = EXPECTED_SIGNATURES[tool_name]
    params = inspect.signature(getattr(server, tool_name)).parameters
    assert tuple(params) == leading + projection, (
        f"{tool_name}: parameter order changed.  Projection parameters must "
        f"stay at the end — inserting one earlier silently re-binds every "
        f"positional caller."
    )
    for name in projection:
        param = params[name]
        assert param.default == PROJECTION_DEFAULTS[name], (
            f"{tool_name}({name}=...) must default to "
            f"{PROJECTION_DEFAULTS[name]!r} so omitting it means no projection"
        )
        assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_SIGNATURES))
def test_no_leading_param_is_named_like_a_projection(tool_name):
    leading, _ = EXPECTED_SIGNATURES[tool_name]
    assert not set(leading) & set(PROJECTION_DEFAULTS)
