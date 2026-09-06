"""Unattached subprojects are reported, never raised over (US-PM-31-9).

Verifies the story criterion:

  > pm_status and the hub rollup report a subproject whose store is not
  > attached as not attached instead of raising

A hub read — the rollup, the dashboards, ``pm_status``, ``GET /api/status`` —
walks every registered subproject.  Before US-PM-31 they all lived in the hub's
own ``.project/projects/``, so "registered" and "readable" were the same thing.
Now each store lives inside its subproject's checkout as a worktree of that
repo's ``projectman`` branch, and the two come apart: a submodule can be
registered, cloned, and still have no store mounted — because nobody has run
``migrate-hub`` on it yet, or because it was cloned without its PM branch.

The rule this module pins is that such a subproject costs the hub *one row*,
not the whole read.  One unmigrated submodule out of ten must not be able to
take down status for the other nine, so:

* every hub read path emits ``{name, prefix, status: "not attached", hint}``
  for it and moves on;
* no ``Store`` is constructed for it — constructing one is what used to raise,
  and the assertion below watches the constructor rather than just the output,
  so a future "just try it and catch the exception" regression is caught even
  though it would produce the same row; and
* the attached subprojects' numbers still land in the totals.

The last test pins the single-project ``pm_status`` shape, because the hub
listing is added to a response other callers parse: in single-project mode the
response must be exactly what it was.
"""

import json

import pytest

from conftest import (
    make_hub_subproject,
    make_unattached_hub_subproject,
    register_hub_subproject_without_store,
)

pytestmark = pytest.mark.usefixtures("all_tool_families")


NOT_ATTACHED = "not attached"


def _story(pm_dir, hub_root, title="A story", points=5):
    """Put one story in a subproject's store so it has numbers to roll up."""
    from projectman.store import Store

    Store(hub_root, project_dir=pm_dir).create_story(title, "Body", points=points)


@pytest.fixture
def mixed_hub(tmp_hub):
    """A hub with one attached subproject (5 points) and two unattached ones.

    The two unattached flavours are deliberately different: ``copied`` has a
    complete, perfectly valid store that simply is not mounted, and ``ghost``
    has nothing on disk at all.  A guard that only handled "the directory is
    missing" would pass on one and fail on the other.
    """
    attached = make_hub_subproject(tmp_hub, "api", "API")
    _story(attached, tmp_hub, points=5)
    make_unattached_hub_subproject(tmp_hub, "copied", "COP")
    register_hub_subproject_without_store(tmp_hub, "ghost")
    return tmp_hub


def _by_name(rows):
    return {r["name"]: r for r in rows}


# ─── The map itself ──────────────────────────────────────────────


def test_the_fixture_really_produces_one_attached_and_two_unattached(mixed_hub):
    """Guard the guard: if the fixture drifted, every test below is vacuous."""
    from projectman.hub.stores import hub_stores

    entries = _by_name(hub_stores(mixed_hub))
    assert entries["api"]["attached"] is True
    assert entries["copied"]["attached"] is False
    assert entries["ghost"]["attached"] is False
    # And "copied" is unattached because of the mount, not missing data.
    assert (entries["copied"]["path"] / "config.yaml").exists()


def test_the_attach_hint_names_both_ways_out(mixed_hub):
    """The hint has to be actionable, and there are exactly two actions."""
    from projectman.hub.stores import attach_hint

    hint = attach_hint("copied")
    assert "migrate-hub" in hint
    assert "add-project" in hint
    assert "copied" in hint


# ─── rollup ──────────────────────────────────────────────────────


def test_rollup_reports_unattached_subprojects_and_still_totals_the_rest(mixed_hub):
    from projectman.hub.rollup import rollup

    data = rollup(mixed_hub)
    projects = _by_name(data["projects"])

    assert projects["api"]["status"] == "active"
    assert projects["api"]["stories"] == 1
    assert projects["api"]["total_points"] == 5

    for name in ("copied", "ghost"):
        row = projects[name]
        assert row["status"] == NOT_ATTACHED
        assert "migrate-hub" in row["hint"]
        assert "add-project" in row["hint"]
        assert "prefix" in row

    # The unattached pair contributes nothing but does not subtract either.
    assert data["total_stories"] == 1
    assert data["total_points"] == 5
    assert data["completion"] == "0%"


def test_rollup_never_constructs_a_store_for_an_unattached_subproject(
    mixed_hub, monkeypatch
):
    """Watch the constructor, not just the row.

    Catching an exception from ``Store(...)`` would produce a plausible-looking
    row too, so the row alone cannot tell "we skipped it" from "we tried it and
    swallowed the error".  The difference matters: opening a half-written store
    is exactly the read that can hang or leave state behind.
    """
    import projectman.hub.rollup as rollup_module
    from projectman.store import Store

    opened = []
    real = rollup_module.Store

    def recording_store(root, *args, project_dir=None, **kwargs):
        opened.append(project_dir)
        return real(root, *args, project_dir=project_dir, **kwargs)

    monkeypatch.setattr(rollup_module, "Store", recording_store)

    rollup_module.rollup(mixed_hub)

    names = {p.parent.name for p in opened if p is not None}
    assert names == {"api"}
    assert isinstance(real, type) and issubclass(real, Store)


def test_rollup_on_a_hub_where_nothing_is_attached_still_answers(tmp_hub):
    """The degenerate case — every subproject unmigrated — is a report, not a crash."""
    from projectman.hub.rollup import rollup

    make_unattached_hub_subproject(tmp_hub, "one")
    make_unattached_hub_subproject(tmp_hub, "two")

    data = rollup(tmp_hub)

    assert [p["status"] for p in data["projects"]] == [NOT_ATTACHED, NOT_ATTACHED]
    assert data["total_points"] == 0
    assert data["completion"] == "0%"


# ─── dashboards ──────────────────────────────────────────────────


def test_dashboards_render_and_name_the_unattached_projects(mixed_hub):
    from projectman.hub.dashboards import generate_dashboards

    generate_dashboards(mixed_hub)

    status = (mixed_hub / ".project" / "dashboards" / "status.md").read_text()
    burndown = (mixed_hub / ".project" / "dashboards" / "burndown.md").read_text()

    assert "copied" in status and "ghost" in status
    assert NOT_ATTACHED in status
    # The hint, not just the status word — a reader of the dashboard should
    # not have to go looking for the fix.
    assert "migrate-hub" in status
    assert "copied" in burndown
    # The attached project is still reported normally.
    assert "api" in status and "api" in burndown


# ─── pm_status ───────────────────────────────────────────────────


def test_pm_status_in_a_hub_lists_subprojects_with_their_attached_state(
    mixed_hub, monkeypatch
):
    import yaml as yaml_mod
    from projectman.server import pm_status

    monkeypatch.chdir(mixed_hub)

    result = yaml_mod.safe_load(pm_status())

    assert result["project"] == "test-hub"
    rows = _by_name(result["subprojects"])
    assert rows["api"]["attached"] is True
    assert rows["copied"]["attached"] is False
    assert rows["ghost"]["attached"] is False
    assert rows["copied"]["status"] == NOT_ATTACHED
    assert "migrate-hub" in rows["copied"]["hint"]
    # An attached row carries no hint — there is nothing to fix.
    assert "hint" not in rows["api"]


def test_pm_status_for_an_attached_subproject_still_reports_its_numbers(
    mixed_hub, monkeypatch
):
    import yaml as yaml_mod
    from projectman.server import pm_status

    monkeypatch.chdir(mixed_hub)

    result = yaml_mod.safe_load(pm_status(prefix="API"))

    assert result["project"] == "api"
    assert result["stories"] == 1
    assert result["total_points"] == 5


def test_pm_status_for_an_unattached_subproject_fails_by_name_not_by_traceback(
    mixed_hub, monkeypatch
):
    """Naming one explicitly is still an error — but a *readable* one.

    Reporting is the behaviour for the listing, not for a direct request:
    ``pm_status(prefix="COP")`` was asked for numbers that do not exist,
    so it says so instead of inventing an empty project.
    """
    from mcp.server.fastmcp.exceptions import ToolError
    from projectman.server import pm_status

    monkeypatch.chdir(mixed_hub)

    with pytest.raises(ToolError) as exc:
        pm_status(prefix="COP")
    assert "copied" in str(exc.value)


def test_single_project_pm_status_shape_is_unchanged(tmp_project, monkeypatch):
    """Pin the non-hub response.

    ``subprojects`` is new, and it must appear *only* in a hub with no project
    named.  Anything parsing pm_status outside a hub sees the same keys it
    always did.
    """
    import yaml as yaml_mod
    from projectman.server import pm_status

    monkeypatch.chdir(tmp_project)

    result = yaml_mod.safe_load(pm_status())

    assert set(result) == {
        "project",
        "epics",
        "stories",
        "tasks",
        "total_points",
        "completed_points",
        "completion",
        "by_status",
    }


# ─── web API ─────────────────────────────────────────────────────


def _client(hub_root):
    from fastapi.testclient import TestClient
    from projectman.store import Store
    from projectman.web.app import app

    app.state.store = Store(hub_root)
    return TestClient(app)


def test_web_status_route_lists_subprojects_and_does_not_500(mixed_hub, monkeypatch):
    monkeypatch.chdir(mixed_hub)

    response = _client(mixed_hub).get("/api/status")

    assert response.status_code == 200
    body = response.json()
    rows = _by_name(body["subprojects"])
    assert rows["api"]["attached"] is True
    assert rows["copied"]["attached"] is False
    assert NOT_ATTACHED in json.dumps(body)
    assert "migrate-hub" in rows["ghost"]["hint"]


def test_web_status_route_for_one_project_omits_the_hub_listing(
    mixed_hub, monkeypatch
):
    """Same rule as pm_status: the per-project response shape is untouched."""
    monkeypatch.chdir(mixed_hub)

    response = _client(mixed_hub).get("/api/status", params={"project": "api"})

    assert response.status_code == 200
    body = response.json()
    assert "subprojects" not in body
    assert body["project"] == "api"


# ─── pm_commit ───────────────────────────────────────────────────
#
# The `skipped_unattached` list these tests pinned belonged to the removed
# `scope="all"` fan-out: since US-PM-35-7 pm_commit acts on exactly one
# store, and an unattached one is refused by name before any git runs
# (`_hub_entry_for_prefix` — see tests/test_hub_commit_push_prefix.py).


# ─── CLI ─────────────────────────────────────────────────────────


def test_projectman_audit_all_says_what_it_skipped(tmp_hub, monkeypatch):
    """`audit --all` walks the same map; a skip it does not mention is a lie."""
    from click.testing import CliRunner
    from projectman.cli import cli

    make_hub_subproject(tmp_hub, "api", "API")
    make_unattached_hub_subproject(tmp_hub, "copied", "COP")
    monkeypatch.chdir(tmp_hub)

    result = CliRunner().invoke(cli, ["audit", "--all"])

    assert result.exit_code == 0, result.output
    assert "Auditing api" in result.output
    assert "copied" in result.output
    assert NOT_ATTACHED in result.output
    assert "migrate-hub" in result.output
