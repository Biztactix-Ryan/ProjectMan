"""US-PM-15-5/-6 — the gated tool families are registered on request.

Every tool in the three families was called zero times across ~14,200
recorded tool calls, so by default their schemas were paid for in every
request and never used. They are gated by config rather than deleted: the
functions are untouched and still importable, and one line in
``.project/config.yaml`` brings a family back.

``changesets`` and ``web`` (US-PM-15-5) are hidden because nobody calls
them. ``maintenance`` (US-PM-15-6) is hidden because it is aimed at the
wrong audience — ``pm_repair``, ``pm_restore``, ``pm_validate_branches``,
``pm_fix_malformed`` and ``pm_push_all`` are human break-glass tools — so
this module also asserts that each of the five is still reachable through
the ``projectman`` CLI, which is where the story says they belong, and that
the shipped guidance sends readers there instead of at the hidden tool.

Everything here is asserted over a real ``tools/list`` (``mcp.list_tools()``,
what the transport serves) and a real ``tools/call`` (the low-level
``CallToolRequest`` handler the transports dispatch to) rather than over the
internal registry dict, so a change that hid a tool from one but not the
other cannot pass.
"""

import itertools
import re

import anyio
import pytest
import yaml
from mcp import types

from pathlib import Path

from projectman.config import (
    GATED_TOOL_FAMILIES,
    enabled_tool_families,
    load_config,
)
from projectman.models import ProjectConfig
from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp as mcp_server,
)

CHANGESET_TOOLS = set(TOOL_FAMILIES["changesets"])
MAINTENANCE_TOOLS = set(TOOL_FAMILIES["maintenance"])
WEB_TOOLS = set(TOOL_FAMILIES["web"])
GATED_TOOLS = CHANGESET_TOOLS | MAINTENANCE_TOOLS | WEB_TOOLS

#: Written out rather than derived, so renaming or dropping a family member
#: has to be a deliberate edit here too.
ALL_OFF = {"changesets": False, "maintenance": False, "web": False}
ALL_ON = {family: True for family in ALL_OFF}

#: Carved out by the story: their zero usage is a wiring gap, not a signal
#: that nobody wants them, and other stories in this epic put them to work.
NEVER_GATED = {"pm_activity", "pm_context", "pm_estimate"}


@pytest.fixture(autouse=True)
def restore_gating():
    """Leave the registry exactly as this module found it."""
    before = gated_tool_state()
    yield
    apply_tool_gating(before)


def listed() -> set[str]:
    """The tool names a client sees from ``tools/list``."""
    return {tool.name for tool in anyio.run(mcp_server.list_tools)}


def call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
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


def all_on() -> set[str]:
    apply_tool_gating(ALL_ON)
    return listed()


def _every_combination() -> list[dict[str, bool]]:
    """All 2^3 flag settings, so "in every configuration" means every one."""
    families = sorted(ALL_OFF)
    return [
        dict(zip(families, values))
        for values in itertools.product([False, True], repeat=len(families))
    ]


# --------------------------------------------------------------- the flags --


def test_every_family_is_off_for_a_plain_project():
    config = ProjectConfig(name="p", prefix="TST")
    assert enabled_tool_families(config) == ALL_OFF


def test_a_hub_gets_changesets_and_still_no_web():
    """The documented inference: a changeset spans projects, so a hub has them.

    ``tools.changesets`` unset means "follow hub mode". The web UI gets no
    such treatment — a hub is no more likely to want the dashboard driven
    from the agent's tool list than a leaf repo is.
    """
    config = ProjectConfig(name="h", prefix="HUB", hub=True)
    assert enabled_tool_families(config) == {**ALL_OFF, "changesets": True}


def test_an_explicit_flag_beats_the_hub_inference():
    hub_off = ProjectConfig(name="h", prefix="HUB", hub=True, tools={"changesets": False})
    leaf_on = ProjectConfig(name="p", prefix="TST", tools={"changesets": True})
    assert enabled_tool_families(hub_off)["changesets"] is False
    assert enabled_tool_families(leaf_on)["changesets"] is True


def test_maintenance_takes_no_hub_inference(tmp_project):
    """US-PM-15-6: break-glass is off until a human writes ``true``.

    ``changesets`` follows ``hub`` because a changeset needs several
    projects to mean anything. Repairing does not — a hub breaks no more
    often than a leaf repo — so the flag is a plain bool with no inference,
    and opting in stays a one-line config change.
    """
    hub = ProjectConfig(name="h", prefix="HUB", hub=True)
    assert enabled_tool_families(hub)["maintenance"] is False

    on = ProjectConfig(name="p", prefix="TST", tools={"maintenance": True})
    assert enabled_tool_families(on)["maintenance"] is True

    config_path = tmp_project / ".project" / "config.yaml"
    data = yaml.safe_load(config_path.read_text())
    data["tools"] = {"maintenance": True}
    config_path.write_text(yaml.dump(data))
    assert enabled_tool_families(load_config(tmp_project)) == {
        **ALL_OFF,
        "maintenance": True,
    }


def test_no_project_hides_everything():
    assert enabled_tool_families(None) == ALL_OFF


def test_opting_in_is_one_line_of_yaml(tmp_project):
    """The opt-in documented in file-formats.md, parsed from a real file."""
    config_path = tmp_project / ".project" / "config.yaml"
    data = yaml.safe_load(config_path.read_text())
    data["tools"] = {"web": True}
    config_path.write_text(yaml.dump(data))

    assert enabled_tool_families(load_config(tmp_project)) == {**ALL_OFF, "web": True}


def test_config_round_trips_through_save(tmp_project):
    """``save_config`` must not lose or corrupt the new section."""
    from projectman.config import save_config

    config = load_config(tmp_project)
    config.tools.web = True
    save_config(config, tmp_project)
    assert load_config(tmp_project).tools.web is True


# ------------------------------------------------------------- tools/list --


def test_the_default_hides_exactly_the_thirteen_gated_tools():
    """AC 1, over a real ``tools/list``: those and nothing else disappear.

    Asserted as a set difference rather than a count, so a change that hid a
    fourteenth tool by accident fails here even if the arithmetic still
    works out.
    """
    everything = all_on()
    apply_tool_gating(ALL_OFF)
    default = listed()

    assert everything - default == GATED_TOOLS
    assert not GATED_TOOLS & default
    assert len(everything) - len(default) == 13
    assert len(default) == 41


def test_each_flag_restores_only_its_own_family():
    everything = all_on()
    families = {
        "changesets": CHANGESET_TOOLS,
        "maintenance": MAINTENANCE_TOOLS,
        "web": WEB_TOOLS,
    }

    for family, tools in families.items():
        apply_tool_gating({**ALL_OFF, family: True})
        only = listed()
        assert tools <= only, family
        assert only == (everything - GATED_TOOLS) | tools, family

    apply_tool_gating(ALL_ON)
    assert listed() == everything


def test_the_carve_outs_are_exposed_in_every_configuration():
    """AC 3: pm_activity, pm_context and pm_estimate are never gated.

    Their zero usage is a wiring gap that US-PM-13 and US-PM-14 close, not a
    signal nobody wants them, so no combination of flags may take them off
    the list — and none of them may appear in a gated family either, which
    is what would let a future edit sweep them up.
    """
    assert not NEVER_GATED & GATED_TOOLS

    for flags in _every_combination():
        apply_tool_gating(flags)
        assert NEVER_GATED <= listed(), flags


def test_gating_is_idempotent():
    apply_tool_gating(ALL_OFF)
    once = listed()
    apply_tool_gating(ALL_OFF)
    assert listed() == once
    apply_tool_gating(ALL_ON)
    apply_tool_gating(ALL_ON)
    assert len(listed()) == len(once) + 13


def test_a_family_survives_a_round_trip_intact():
    """Re-registering must hand back the same tools, schemas and all."""
    apply_tool_gating(ALL_ON)
    everything = {
        t.name: t for t in anyio.run(mcp_server.list_tools) if t.name in GATED_TOOLS
    }
    apply_tool_gating(ALL_OFF)
    apply_tool_gating(ALL_ON)
    after = {
        t.name: t for t in anyio.run(mcp_server.list_tools) if t.name in GATED_TOOLS
    }

    assert set(after) == GATED_TOOLS
    for name, tool in after.items():
        assert tool.inputSchema == everything[name].inputSchema
        assert tool.description == everything[name].description


def test_gating_reads_the_project_config_when_asked_to(tmp_project, monkeypatch):
    """``apply_tool_gating()`` with no argument resolves the project on disk."""
    config_path = tmp_project / ".project" / "config.yaml"
    data = yaml.safe_load(config_path.read_text())
    data["tools"] = {"web": True}
    config_path.write_text(yaml.dump(data))

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    assert apply_tool_gating() == {**ALL_OFF, "web": True}
    assert WEB_TOOLS <= listed()
    assert not CHANGESET_TOOLS & listed()


def test_gating_outside_a_project_hides_everything_rather_than_raising(
    tmp_path, monkeypatch
):
    """An MCP server can be started anywhere; startup must not depend on a project."""
    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert apply_tool_gating() == ALL_OFF
    assert not GATED_TOOLS & listed()


# ------------------------------------------------------------- tools/call --


@pytest.mark.parametrize("name", sorted(GATED_TOOLS))
def test_calling_a_hidden_tool_fails_the_way_an_unknown_tool_does(name):
    """AC 1's other half: hidden means hidden at ``tools/call`` too.

    Not a crash and not a half-executed call — the same ``Unknown tool``
    that any misspelled name gets, with ``is_error`` set, so a client that
    cached an old tool list gets a clean answer instead of a broken one.
    """
    apply_tool_gating(ALL_OFF)

    is_error, text = call_over_the_wire(name, {})
    assert is_error, (name, text)
    assert "Unknown tool" in text, (name, text)
    # And it is not a soft error body either (US-PM-2).
    assert not text.lstrip().startswith("error:"), (name, text)


def test_an_enabled_tool_is_callable_again():
    apply_tool_gating({**ALL_OFF, "web": True})
    is_error, text = call_over_the_wire("pm_web_status", {})
    assert not is_error, text
    assert "Unknown tool" not in text
    assert yaml.safe_load(text) == {"running": False}


# ------------------------------------------------- the code stays reachable --


def test_the_hidden_functions_are_still_importable_and_callable():
    """Gating is registration-only: nothing is deleted, nothing is stubbed.

    This is what keeps ``tests/test_changeset.py`` and the web tests working
    against the real code while the families are hidden from agents.
    """
    apply_tool_gating(ALL_OFF)

    from projectman import server

    for name in sorted(GATED_TOOLS):
        fn = getattr(server, name)
        assert callable(fn), name

    assert yaml.safe_load(server.pm_web_status()) == {"running": False}


# ------------------------------------------- the gate, driven from real YAML --
#
# The tests above drive ``apply_tool_gating`` with an explicit mapping, which
# proves the registry surgery. These drive it the way the server does — with
# no argument, off a ``.project/config.yaml`` on disk — so the config parsing
# and the registry surgery are asserted end to end (US-PM-15-1).


def write_config(root, **overrides) -> None:
    """Rewrite ``tmp_project``'s config, replacing keys wholesale."""
    config_path = root / ".project" / "config.yaml"
    data = yaml.safe_load(config_path.read_text())
    data.update(overrides)
    config_path.write_text(yaml.dump(data))


def enter(monkeypatch, root) -> None:
    """Make ``root`` the project ``load_config()`` finds."""
    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(root)


@pytest.mark.parametrize(
    "tools_section",
    [pytest.param(None, id="no-tools-section"), pytest.param({}, id="empty-tools-section")],
)
def test_a_default_config_on_disk_hides_exactly_the_thirteen(
    tmp_project, monkeypatch, tools_section
):
    """AC 1 end to end: an untouched config, and an explicit empty section.

    ``tools:`` absent is what every existing repo has; ``tools: {}`` is what
    a half-finished edit leaves behind. Both must mean "every family off",
    and the difference from the everything-on list must be exactly the
    thirteen — no fourteenth tool swept up, no other tool lost.
    """
    everything = all_on()
    if tools_section is not None:
        write_config(tmp_project, tools=tools_section)

    enter(monkeypatch, tmp_project)
    assert apply_tool_gating() == ALL_OFF

    default = listed()
    assert not GATED_TOOLS & default
    assert everything - default == GATED_TOOLS
    assert default == everything - GATED_TOOLS


@pytest.mark.parametrize(
    "family, flag",
    [
        ("web", {"web": True}),
        ("changesets", {"changesets": True}),
        ("maintenance", {"maintenance": True}),
    ],
)
def test_one_flag_in_the_file_restores_exactly_that_family(
    tmp_project, monkeypatch, family, flag
):
    """AC 1's converse, as an exact set: opting in adds that family only."""
    everything = all_on()
    hidden = TOOL_FAMILIES[family]

    write_config(tmp_project, tools=flag)
    enter(monkeypatch, tmp_project)
    apply_tool_gating()

    assert listed() == (everything - GATED_TOOLS) | set(hidden)
    assert len(hidden) == {"web": 3, "changesets": 5, "maintenance": 5}[family]


def test_a_hub_on_disk_gets_changesets_and_can_still_turn_them_off(
    tmp_hub, monkeypatch
):
    """The hub inference, over a real ``tools/list`` rather than the flags.

    ``tools.changesets`` unset in a hub config exposes the five changeset
    tools and still none of the three web ones; writing ``false`` puts them
    back out of sight.
    """
    everything = all_on()
    enter(monkeypatch, tmp_hub)

    assert apply_tool_gating() == {**ALL_OFF, "changesets": True}
    assert listed() == (everything - GATED_TOOLS) | CHANGESET_TOOLS

    write_config(tmp_hub, tools={"changesets": False})
    assert apply_tool_gating() == ALL_OFF
    assert not GATED_TOOLS & listed()


@pytest.mark.parametrize(
    "tools_value",
    [
        pytest.param("web", id="string-instead-of-mapping"),
        pytest.param(["web"], id="list-instead-of-mapping"),
        pytest.param({"web": "yes please"}, id="unparseable-flag"),
    ],
)
def test_a_malformed_tools_section_hides_the_families_instead_of_raising(
    tmp_project, monkeypatch, tools_value
):
    """Startup must survive a config a human mistyped.

    ``load_config`` rejects these, so the gate has to fail closed: hidden
    families, no exception out of ``apply_tool_gating``, and the rest of the
    tool list untouched.
    """
    everything = all_on()
    write_config(tmp_project, tools=tools_value)
    enter(monkeypatch, tmp_project)

    assert apply_tool_gating() == ALL_OFF
    assert listed() == everything - GATED_TOOLS


# ------------------------------------------------------ applied at startup --


def test_run_server_applies_the_gating_at_startup(tmp_project, monkeypatch):
    """The config that counts is the one on disk when the server comes up.

    Import-time gating alone is not enough: the module may be imported from
    anywhere, and ``PROJECTMAN_ROOT`` or the cwd can be set afterwards. This
    writes a config *after* import, hides the families by hand, and then
    lets ``run_server`` run — the web family must come back without anyone
    calling ``apply_tool_gating`` directly.
    """
    from projectman import server

    everything = all_on()
    write_config(tmp_project, tools={"web": True})
    enter(monkeypatch, tmp_project)

    # Whatever import time decided, start from both families hidden.
    apply_tool_gating(ALL_OFF)
    assert not GATED_TOOLS & listed()

    ran = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: ran.append(kwargs))
    server.run_server(transport="stdio")

    assert ran == [{"transport": "stdio"}]
    assert listed() == (everything - GATED_TOOLS) | WEB_TOOLS


# ------------------------------------------- break-glass, reachable by CLI --
#
# AC 2 has three parts. The part above hides the five ``maintenance`` tools
# from ``tools/list``; this one is the promise that hiding them took
# nothing away — a human whose project is broken still has a way in. Each
# test drives the real ``projectman`` command through click's CliRunner,
# with the family hidden from MCP throughout, so a CLI command deleted or
# renamed out from under a hidden tool fails here.

from click.testing import CliRunner  # noqa: E402

from projectman.cli import cli  # noqa: E402

# The hub-with-bare-remotes rig, reused so ``push-all --dry-run`` is
# exercised against real git rather than a stub.
from tests.test_coordinated_push import (  # noqa: E402,F401
    _git,
    _remote_sha,
    hub_with_remotes,
)

#: Every hidden break-glass tool and the command that reaches it.
CLI_FOR_TOOL = {
    "pm_repair": "repair",
    "pm_restore": "restore",
    "pm_validate_branches": "validate-branches",
    "pm_fix_malformed": "fix-malformed",
    "pm_push_all": "push-all",
}


def test_every_maintenance_tool_is_named_in_the_cli_map():
    """The map above must cover the family, not a stale subset of it."""
    assert set(CLI_FOR_TOOL) == MAINTENANCE_TOOLS


@pytest.mark.parametrize("tool, command", sorted(CLI_FOR_TOOL.items()))
def test_a_hidden_break_glass_tool_still_has_a_cli_command(tool, command):
    """AC 2: hidden from the agent, reachable from a shell."""
    apply_tool_gating(ALL_OFF)
    assert tool not in listed()

    result = CliRunner().invoke(cli, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert command in result.output


def test_the_cli_restores_a_quarantined_file_while_the_tool_is_hidden(
    tmp_project, monkeypatch
):
    """``projectman restore`` really moves the file, not just prints help.

    The end-to-end proof for AC 2: with ``pm_restore`` off the tool list, a
    file sitting in ``malformed/`` still gets back to ``tasks/``.
    """
    apply_tool_gating(ALL_OFF)
    assert "pm_restore" not in listed()

    proj = tmp_project / ".project"
    (proj / "stories" / "TST-1.md").write_text(
        "---\nid: TST-1\ntitle: A story\nstatus: ready\npriority: should\n"
        "created: 2026-08-21\nupdated: 2026-08-21\n---\n\nBody.\n"
    )
    malformed = proj / "malformed"
    malformed.mkdir()
    (malformed / "TST-1-1.md").write_text(
        "---\nid: TST-1-1\nstory_id: TST-1\ntitle: A task\nstatus: todo\n"
        "created: 2026-08-21\nupdated: 2026-08-21\n---\n\nBody.\n"
    )

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    result = CliRunner().invoke(cli, ["restore", "TST-1-1.md"])

    assert result.exit_code == 0, result.output
    assert (proj / "tasks" / "TST-1-1.md").exists()
    assert not malformed.exists()
    assert "pm_restore" not in listed()


def test_the_cli_fixes_a_malformed_file_while_the_tool_is_hidden(
    tmp_project, monkeypatch
):
    """The same end-to-end proof for ``projectman fix-malformed``."""
    apply_tool_gating(ALL_OFF)
    assert "pm_fix_malformed" not in listed()

    proj = tmp_project / ".project"
    malformed = proj / "malformed"
    malformed.mkdir()
    (malformed / "broken.md").write_text("no frontmatter at all\n")

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    result = CliRunner().invoke(
        cli,
        [
            "fix-malformed",
            "broken.md",
            "--id",
            "TST-2",
            "--title",
            "Recovered story",
            "--type",
            "story",
        ],
    )

    assert result.exit_code == 0, result.output
    fixed = proj / "stories" / "TST-2.md"
    assert fixed.exists()
    assert "Recovered story" in fixed.read_text()
    assert not (malformed / "broken.md").exists()


def test_the_cli_repairs_a_hub_while_the_tool_is_hidden(tmp_hub, monkeypatch):
    """``projectman repair`` really rebuilds the hub, not just prints help.

    The end-to-end proof for ``pm_repair``: with the tool off the list, an
    unregistered project on disk still gets discovered, registered and
    initialised, and the ``REPAIR.md`` report still lands.
    """
    apply_tool_gating(ALL_OFF)
    assert "pm_repair" not in listed()

    (tmp_hub / "projects" / "api").mkdir(parents=True)

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_hub)
    result = CliRunner().invoke(cli, ["repair"])

    assert result.exit_code == 0, result.output
    assert "Hub Repair Report" in result.output
    assert "api" in result.output

    config = yaml.safe_load((tmp_hub / ".project" / "config.yaml").read_text())
    assert config["projects"] == ["api"], config
    assert (tmp_hub / ".project" / "projects" / "api" / "config.yaml").exists()
    report = tmp_hub / ".project" / "REPAIR.md"
    assert report.exists()
    assert "Hub Repair Report" in report.read_text()
    assert "pm_repair" not in listed()


def test_the_cli_validates_branches_while_the_tool_is_hidden(tmp_hub, monkeypatch):
    """``projectman validate-branches`` reports, and exits on the verdict.

    Two real runs, not a ``--help`` smoke: a hub with nothing to check gets
    the clean message and exit 0; a hub whose registered project is not on
    disk gets it named in the report and exit 1. Both with ``pm_validate_branches``
    off the tool list.
    """
    apply_tool_gating(ALL_OFF)
    assert "pm_validate_branches" not in listed()

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_hub)

    clean = CliRunner().invoke(cli, ["validate-branches"])
    assert clean.exit_code == 0, clean.output
    assert "No submodules with tracking branches to validate." in clean.output

    write_config(tmp_hub, projects=["ghost"])
    broken = CliRunner().invoke(cli, ["validate-branches"])

    assert broken.exit_code == 1, broken.output
    assert "Missing directories:" in broken.output
    assert "ghost" in broken.output
    assert "pm_validate_branches" not in listed()


def test_the_cli_dry_runs_a_coordinated_push_while_the_tool_is_hidden(
    hub_with_remotes, monkeypatch
):
    """``projectman push-all --dry-run`` plans a real push and pushes nothing.

    A real hub with two submodules and bare remotes, both carrying unpushed
    commits. The command must name them in its plan while ``pm_push_all`` is
    off the tool list — and every remote must be byte-identical afterwards.
    """
    apply_tool_gating(ALL_OFF)
    assert "pm_push_all" not in listed()

    hub = hub_with_remotes["hub"]
    for name in ("api", "web"):
        sub = hub / "projects" / name
        (sub / "dryrun.txt").write_text(f"{name} dry run")
        _git(["add", "."], sub)
        _git(["commit", "-m", f"{name}: dry run"], sub)
    _git(["add", "projects/api", "projects/web"], hub)
    _git(["commit", "-m", "update refs for dry run"], hub)

    before = {
        name: _remote_sha(hub_with_remotes[f"{name}_bare"])
        for name in ("api", "web", "hub")
    }

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["push-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.output)
    assert payload["pushed"] is False, payload
    report = payload["report"]
    assert "Dry Run" in report, report
    assert "would push" in report, report
    for name in ("api", "web"):
        assert name in report, report

    after = {
        name: _remote_sha(hub_with_remotes[f"{name}_bare"])
        for name in ("api", "web", "hub")
    }
    assert after == before, "a dry run pushed something"
    assert "pm_push_all" not in listed()


def test_a_failing_break_glass_command_exits_nonzero(tmp_project, monkeypatch):
    """A break-glass command that cannot do its job must say so.

    Reachable is not the same as useful: if ``restore`` silently exited 0 on
    a missing file, a human recovering a project would be told the opposite
    of the truth.
    """
    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    result = CliRunner().invoke(cli, ["restore", "nope.md"])

    assert result.exit_code == 1, result.output
    assert "Error" in result.output


# ------------------------------------------- the carve-outs (US-PM-15-3) --
#
# AC 3 carried all the way out. ``pm_activity``, ``pm_context`` and
# ``pm_estimate`` were called ~zero times in the same studies that condemned
# the three gated families, and the story is explicit that this is a
# *wiring* gap — US-PM-13 and US-PM-14 put them to work — not a signal that
# nobody wants them. So the promise is stronger than "not in a gated family
# today": they stay on a real ``tools/list`` under every configuration a
# server can come up in, they stay callable, no future edit can sweep them
# into a family, and the guidance that is supposed to drive them still names
# the MCP tool rather than redirecting agents at a CLI the way the
# break-glass five were.

from tests.test_skill_release_instructions import (  # noqa: E402
    REPO_ROOT,
    TEMPLATES,
    _rendered_skills,
    _skill_templates,
)

MCP_TOOLS_DOC = REPO_ROOT / "docs" / "reference" / "mcp-tools.md"

#: A real, read-only ``tools/call`` for each carve-out. ``pm_estimate`` needs
#: something to size, which the test creates first.
CARVE_OUT_CALLS = {
    "pm_activity": {"limit": 1},
    "pm_context": {"limit": 1, "max_doc_chars": 200},
    "pm_estimate": {"id": "US-TST-1"},
}

#: ``projectman <verb>`` — the shape of the redirect the break-glass tools
#: got. None of the three may acquire one: a carve-out told to go to the CLI
#: is a carve-out in name only.
CLI_REDIRECT = re.compile(r"projectman\s+(activity|context|estimate)\b")


def _config_id(flags: dict) -> str:
    on = [family for family, value in sorted(flags.items()) if value]
    return "+".join(on) if on else "all-off"


def _gating_notes(text: str) -> str:
    """Every ``> **Off by default.**`` blockquote in the reference page."""
    blocks: list[str] = []
    block: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            block.append(line)
            continue
        if block:
            blocks.append("\n".join(block))
            block = []
    if block:
        blocks.append("\n".join(block))
    return "\n".join(b for b in blocks if "Off by default" in b)


# ---------------------------------------------------- (a) always listed --


@pytest.mark.parametrize(
    "tools_section",
    [pytest.param(None, id="no-tools-section")]
    + [pytest.param(flags, id=_config_id(flags)) for flags in _every_combination()],
)
def test_the_carve_outs_are_listed_for_every_config_on_disk(
    tmp_project, monkeypatch, tools_section
):
    """An untouched config and all eight flag settings, driven off real YAML.

    ``test_the_carve_outs_are_exposed_in_every_configuration`` proves the same
    thing through an explicit mapping; this one goes through ``load_config``,
    so a config parse that mislabelled a family could not hide here.
    """
    if tools_section is not None:
        write_config(tmp_project, tools=tools_section)
    enter(monkeypatch, tmp_project)

    resolved = apply_tool_gating()
    assert resolved == (ALL_OFF if tools_section is None else tools_section)
    assert NEVER_GATED <= listed(), tools_section


def test_the_carve_outs_are_listed_in_hub_mode(tmp_hub, monkeypatch):
    """The one configuration that turns a family on by inference."""
    enter(monkeypatch, tmp_hub)

    assert apply_tool_gating() == {**ALL_OFF, "changesets": True}
    assert NEVER_GATED <= listed()


def test_the_carve_outs_are_listed_outside_any_project(tmp_path, monkeypatch):
    """No project at all is the harshest case: every family resolves off."""
    enter(monkeypatch, tmp_path)

    assert apply_tool_gating() == ALL_OFF
    assert NEVER_GATED <= listed()


@pytest.mark.parametrize(
    "tools_value",
    [
        pytest.param("web", id="string-instead-of-mapping"),
        pytest.param(["web"], id="list-instead-of-mapping"),
        pytest.param({"web": "yes please"}, id="unparseable-flag"),
    ],
)
def test_the_carve_outs_survive_a_malformed_tools_section(
    tmp_project, monkeypatch, tools_value
):
    """Failing closed on a mistyped config must not close on the carve-outs."""
    write_config(tmp_project, tools=tools_value)
    enter(monkeypatch, tmp_project)

    assert apply_tool_gating() == ALL_OFF
    assert NEVER_GATED <= listed()


# -------------------------------------------------------- (b) callable --


def test_the_call_table_covers_every_carve_out():
    assert set(CARVE_OUT_CALLS) == NEVER_GATED


@pytest.mark.parametrize("name", sorted(CARVE_OUT_CALLS))
def test_each_carve_out_is_callable_under_the_default_config(
    tmp_project, monkeypatch, name
):
    """Listed is not the same as reachable — each one answers a real call.

    Default config, so every gated family is hidden around it. A success, not
    an ``Unknown tool`` and not a soft ``error:`` body (US-PM-2).
    """
    enter(monkeypatch, tmp_project)
    assert apply_tool_gating() == ALL_OFF

    # pm_estimate needs an item to size; the other two do not mind it.
    created, body = call_over_the_wire(
        "pm_create_story", {"title": "Sized", "description": "For estimation."}
    )
    assert not created, body
    assert "US-TST-1" in body

    is_error, text = call_over_the_wire(name, CARVE_OUT_CALLS[name])
    assert "Unknown tool" not in text, (name, text)
    assert not is_error, (name, text)
    assert not text.lstrip().startswith("error:"), (name, text)


# ------------------------------------------- (c) unswept by a later edit --


def test_no_carve_out_can_be_named_in_a_gated_family():
    """The pin: adding one to a family — or to the family list — fails here.

    Stated over ``TOOL_FAMILIES`` and ``GATED_TOOL_FAMILIES`` directly rather
    than over a tool list, so it fails at the edit that adds the name, not
    later at whichever configuration happens to hide it.
    """
    for family, names in sorted(TOOL_FAMILIES.items()):
        for name in sorted(NEVER_GATED):
            assert name not in names, f"{name} was swept into TOOL_FAMILIES[{family!r}]"
    assert not NEVER_GATED & GATED_TOOLS
    assert not NEVER_GATED & set(GATED_TOOL_FAMILIES)

    # And not vacuous: all three are really registered tools, so renaming one
    # out of existence cannot satisfy the assertions above.
    apply_tool_gating(ALL_OFF)
    assert NEVER_GATED <= listed()


# ------------------------------------------- (d) the guidance still calls --


@pytest.mark.parametrize("name", sorted(NEVER_GATED))
def test_a_skill_template_still_names_the_carve_out_as_an_mcp_tool(name):
    """Something in the guidance still sends agents at the MCP tool.

    Presence of the *name*, deliberately: whether the mention is a named step
    with a call form is US-PM-13's and US-PM-14's criterion, pinned in
    ``test_skill_guidance_tools.py``. What this file owns is the weaker,
    gating-shaped promise — the guidance was not rewritten around the tool
    being gone.
    """
    callers = [
        p.name for p in _skill_templates() if re.search(rf"\b{name}\b", p.read_text())
    ]
    assert callers, f"no skill template names {name}"


@pytest.mark.parametrize("name", sorted(NEVER_GATED))
def test_the_reference_documents_the_carve_out_as_an_ungated_tool(name):
    """Documented as a tool, and named in no ``Off by default`` note."""
    text = MCP_TOOLS_DOC.read_text()
    notes = _gating_notes(text)
    assert "pm_repair" in notes, "the gating notes moved — this test reads nothing"

    assert f"### {name}(" in text, f"{name} has no section in {MCP_TOOLS_DOC.name}"
    assert name not in notes, f"{name} is listed as gated in {MCP_TOOLS_DOC.name}"


def test_no_guidance_redirects_a_carve_out_to_the_cli():
    """The break-glass five got a CLI equivalent; these three must not.

    ``projectman repair`` is the right answer for a hidden tool. For a tool
    that is on the list, the same sentence would send agents away from the
    MCP call the wiring stories exist to make them use.
    """
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in [*_skill_templates(), *_rendered_skills(), MCP_TOOLS_DOC]
        for match in CLI_REDIRECT.finditer(path.read_text())
    ]
    assert not offenders, "guidance redirects a carve-out to the CLI:\n" + "\n".join(
        offenders
    )


# ------------------------------- break-glass, redirected in the guidance --
#
# AC 2's third part, and the mirror of ``test_no_guidance_redirects_a_carve_out
# _to_the_cli``. Hiding the five from ``tools/list`` is only safe if the
# guidance an agent actually reads was moved with them: the shipped skill and
# agent templates, the rendered copies under ``.claude/`` that a checkout
# loads, and the tool reference must send a human at ``projectman <verb>``
# and must not tell an agent to call the hidden tool.

from projectman.cli import CLAUDE_SKILLS  # noqa: E402

RENDERED_CLAUDE = REPO_ROOT / ".claude"

#: ``→ `pm_repair```, ``call pm_repair``, ``pm_repair(...)`` — the forms this
#: guidance uses to dispatch an agent at a tool. A bare mention in prose (the
#: agent template explains *why* fix-malformed is a CLI command) is not one.
_BREAK_GLASS_NAMES = "|".join(sorted(CLI_FOR_TOOL))
CALL_FORM = re.compile(
    rf"(?:→\s*`?|\b(?:call|use|invoke|run)\s+`?)(?:{_BREAK_GLASS_NAMES})\b"
    rf"|`(?:{_BREAK_GLASS_NAMES})\(",
    re.IGNORECASE,
)


def _guidance_pairs() -> list[tuple[Path, Path]]:
    """Every shipped guidance template paired with its rendered copy."""
    pairs = [(TEMPLATES / "agent_pm.md.j2", RENDERED_CLAUDE / "agents" / "pm.md")]
    pairs += [
        (TEMPLATES / template, RENDERED_CLAUDE / "skills" / name / "SKILL.md")
        for name, template in CLAUDE_SKILLS
    ]
    present = [(t, r) for t, r in pairs if t.exists() and r.exists()]
    assert present, "no rendered guidance found — this test would read nothing"
    return present


def _cli_mentions(text: str) -> set[str]:
    """Which of the five ``projectman <verb>`` redirects a file carries."""
    return {
        command
        for command in CLI_FOR_TOOL.values()
        if re.search(rf"projectman {re.escape(command)}\b", text)
    }


def test_no_guidance_tells_an_agent_to_call_a_break_glass_tool():
    """Nothing an agent reads may dispatch it at a tool that is not there.

    Checked over the templates *and* the rendered ``.claude/`` copies, since
    a stale render is what a checkout actually loads.
    """
    offenders = [
        f"{path}: {match.group(0)}"
        for path in [*_skill_templates(), *(r for _, r in _guidance_pairs())]
        for match in CALL_FORM.finditer(path.read_text())
    ]
    assert not offenders, "guidance still calls a hidden tool:\n" + "\n".join(offenders)


def test_the_guidance_names_the_cli_for_every_break_glass_tool():
    """Each of the five has a ``projectman <verb>`` in what ships."""
    shipped = "\n".join(
        path.read_text()
        for path in [
            *_skill_templates(),
            *(r for _, r in _guidance_pairs()),
            MCP_TOOLS_DOC,
        ]
    )
    missing = sorted(set(CLI_FOR_TOOL.values()) - _cli_mentions(shipped))
    assert not missing, f"no guidance names the CLI for: {missing}"


@pytest.mark.parametrize("template, rendered", _guidance_pairs(), ids=lambda p: p.name)
def test_a_rendered_copy_carries_the_same_redirects_as_its_template(
    template, rendered
):
    """A rendered copy that lagged the template would still point at MCP."""
    assert _cli_mentions(rendered.read_text()) == _cli_mentions(template.read_text())


@pytest.mark.parametrize("tool, command", sorted(CLI_FOR_TOOL.items()))
def test_the_reference_documents_the_break_glass_tool_as_gated(tool, command):
    """``mcp-tools.md`` marks each one off-by-default and names its CLI.

    Both halves per tool: the family note at the top lists the name, and the
    tool's own section carries the break-glass line with the command, so a
    reader who lands on either learns the same thing.
    """
    text = MCP_TOOLS_DOC.read_text()
    assert tool in _gating_notes(text), f"{tool} is not in an 'Off by default' note"

    heading = f"### {tool}("
    assert heading in text, f"{tool} has no section in {MCP_TOOLS_DOC.name}"
    section = text.split(heading, 1)[1].split("\n### ", 1)[0]
    assert "Break-glass" in section, f"{tool}'s section does not say break-glass"
    assert f"projectman {command}" in section, (
        f"{tool}'s section does not name 'projectman {command}'"
    )
