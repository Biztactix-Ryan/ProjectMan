"""US-PM-27-1 — the changeset feature is gone, and old projects still load.

US-PM-27's first acceptance criterion: "No pm_changeset tool or changeset CLI
command exists and the changesets module is gone". Deleting a feature is only
half the job — the other half is that a store written *before* the deletion
still opens. ``.project/config.yaml`` files in the wild carry a
``next_changeset_id`` counter that nothing reads any more, and a config loader
that rejected it would turn "we removed a feature" into "every existing project
is broken".

So this module pins five things, each against the real artefact rather than a
grep of the source:

1. ``projectman.changesets`` does not import;
2. no tool the MCP server registers is named ``pm_changeset*`` — asserted over
   a real ``tools/list`` with *every* gated family switched on, so a tool
   merely hidden behind a config flag would still be caught;
3. the click CLI has no ``changeset`` group and no ``changeset-status``
   command, at the top level or nested inside any subgroup;
4. ``projectman.models`` exposes no name containing "Changeset";
5. ``load_config`` — the real loader, off a real file — accepts a config that
   still carries ``next_changeset_id``.
"""

import importlib

import anyio
import pytest
import yaml

from projectman.config import clear_config_cache, load_config
from projectman.models import ProjectConfig
from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp as mcp_server,
)

#: The prefix every one of the five deleted tools shared.
TOOL_PREFIX = "pm_changeset"


@pytest.fixture
def every_family_registered():
    """Run the body with all gated families on, and restore what was there.

    Gating removes tools from the registry, so a check run under the default
    configuration cannot tell "deleted" from "currently hidden". Switching
    everything on makes the assertion about the code rather than about the
    ambient ``.project/config.yaml``.
    """
    before = gated_tool_state()
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    try:
        yield
    finally:
        apply_tool_gating(before)


def _registered_tool_names() -> set[str]:
    """The names a real ``tools/list`` serves right now."""
    return {tool.name for tool in anyio.run(mcp_server.list_tools)}


def _command_paths(group, prefix=()) -> set[tuple[str, ...]]:
    """Every command in a click group, depth-first, as name tuples."""
    paths = set()
    for name, command in getattr(group, "commands", {}).items():
        here = prefix + (name,)
        paths.add(here)
        paths |= _command_paths(command, here)
    return paths


# ------------------------------------------------------ (1) the module is gone --


def test_importing_the_changesets_module_raises_importerror():
    with pytest.raises(ImportError):
        importlib.import_module("projectman.changesets")


def test_the_import_check_is_not_vacuous():
    """A control: the same call on a module that *does* exist must succeed.

    Without this, a typo in the module path above would make the test pass for
    the wrong reason forever.
    """
    assert importlib.import_module("projectman.config") is not None


# --------------------------------------------------------- (2) no MCP tool --


def test_no_registered_mcp_tool_is_a_changeset_tool(every_family_registered):
    names = _registered_tool_names()
    offenders = sorted(n for n in names if n.startswith(TOOL_PREFIX))
    assert offenders == [], f"changeset tools still served by tools/list: {offenders}"
    # The list is otherwise populated, so an empty registry cannot pass this.
    assert "pm_grab" in names


def test_no_gated_tool_family_lists_a_changeset_tool():
    """``changeset`` used to be a gated family; the family must be gone too."""
    assert "changeset" not in TOOL_FAMILIES
    for family, tools in TOOL_FAMILIES.items():
        offenders = [t for t in tools if t.startswith(TOOL_PREFIX)]
        assert offenders == [], f"family {family!r} still names {offenders}"


def test_the_server_module_exposes_no_changeset_tool_function():
    from projectman import server

    offenders = sorted(n for n in dir(server) if n.startswith(TOOL_PREFIX))
    assert offenders == [], f"projectman.server still defines {offenders}"


# --------------------------------------------------------- (3) no CLI command --


def test_the_cli_has_no_changeset_group_or_changeset_status_command():
    from projectman.cli import cli

    assert "changeset" not in cli.commands
    assert "changeset-status" not in cli.commands
    # Nested too: a subgroup could just as easily carry them.
    offenders = sorted(
        "/".join(path)
        for path in _command_paths(cli)
        if any("changeset" in part for part in path)
    )
    assert offenders == [], f"CLI still exposes {offenders}"
    # Control: the group really was walked.
    assert ("serve",) in _command_paths(cli)


# ------------------------------------------------------------ (4) no models --


def test_projectman_models_exposes_no_changeset_name():
    from projectman import models

    offenders = sorted(n for n in dir(models) if "changeset" in n.lower())
    assert offenders == [], f"projectman.models still exposes {offenders}"


def test_projectconfig_has_no_changeset_field():
    offenders = sorted(f for f in ProjectConfig.model_fields if "changeset" in f.lower())
    assert offenders == [], f"ProjectConfig still declares {offenders}"


# ------------------------------------- (5) a pre-removal project still loads --


def _write_config(root, **extra):
    project = root / ".project"
    project.mkdir(exist_ok=True)
    data = {
        "name": "legacy-project",
        "prefix": "TST",
        "description": "written before US-PM-27",
        "hub": False,
        "next_story_id": 4,
        "next_epic_id": 2,
        "next_sprint_id": 3,
        "projects": [],
        **extra,
    }
    (project / "config.yaml").write_text(yaml.dump(data))
    return data


def test_the_real_loader_accepts_a_config_carrying_next_changeset_id(tmp_path):
    """An untouched pre-removal ``config.yaml`` must still open, unchanged.

    ``load_config`` caches per resolved root, so the cache is cleared around
    the read — otherwise a hit from another test's project could answer here
    and the loader would never actually be exercised.
    """
    _write_config(tmp_path, next_changeset_id=9)
    clear_config_cache(tmp_path)
    try:
        config = load_config(tmp_path)
    finally:
        clear_config_cache(tmp_path)

    assert isinstance(config, ProjectConfig)
    assert config.name == "legacy-project"
    assert config.next_story_id == 4
    assert not hasattr(config, "next_changeset_id")


def test_the_model_itself_ignores_the_legacy_key(tmp_path):
    """Straight at the model, so the tolerance is not an accident of the loader."""
    data = _write_config(tmp_path, next_changeset_id=9)
    config = ProjectConfig(**data)
    assert config.prefix == "TST"
    assert "next_changeset_id" not in config.model_dump()


def test_the_loader_does_not_rewrite_the_legacy_key_out_of_the_file(tmp_path):
    """Loading is a read: an old project keeps its dead key until it is saved."""
    _write_config(tmp_path, next_changeset_id=9)
    clear_config_cache(tmp_path)
    try:
        load_config(tmp_path)
    finally:
        clear_config_cache(tmp_path)
    on_disk = yaml.safe_load((tmp_path / ".project" / "config.yaml").read_text())
    assert on_disk["next_changeset_id"] == 9
