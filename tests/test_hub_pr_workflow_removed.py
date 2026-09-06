"""US-PM-27-2 — the hub PR / ref-update / rebase-resolution workflow is gone.

US-PM-27's second acceptance criterion: "hub/registry.py no longer contains
feature-branch or PR or hub-ref-update or rebase-conflict code".

Pass 2 of the removal (US-PM-27-7) deleted sixteen functions from
``src/projectman/hub/registry.py``. One thing had to stay, because live
callers use it: :func:`log_ref_update`, reached by ``sync``. So "the code is
gone" is not a whole-file grep — it is a claim about which names survived.

:func:`_get_deploy_branch` was kept back then too, for the git-status
dashboard. US-PM-35-8 took it: the dashboard now reports each subproject's
*store* through ``worktree.store_git_state`` and has no opinion about how a
subproject deploys, so its last hub-side reader went with the alignment
scoring (``REMOVED_LATER`` below).

US-PM-35-6 later took the rest of the cross-project push with it, including
``hub_push_with_rebase`` and ``validate_not_on_deploy_branch``, so the
rebase-abort scenario this module used to drive has no function to drive.

This module pins three things:

1. none of the sixteen removed names is an attribute of the module — asserted
   against the imported module rather than its text, so a name that came back
   via a re-export would still be caught;
2. the module source carries no ``gh`` CLI pull-request invocation, no
   "pull request" wording, and no submodule-ref auto-resolution wording;
3. no tool the MCP server registers and no click command is named for the
   feature-branch, create-pr, pr-status or deploy-branch workflow — the tool
   check runs with every gated family switched on, so a tool merely hidden
   behind a config flag would still be caught.

The functions that were *kept* are asserted present too (below), so a future
over-eager deletion fails here instead of at a caller.
"""

import re
from pathlib import Path

import anyio
import pytest

from projectman.hub import registry
from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp as mcp_server,
)


#: The sixteen names US-PM-27-7 removed from ``hub/registry.py``.
REMOVED_NAMES = [
    "create_feature_branch",
    "list_feature_branches",
    "_slugify",
    "create_pr",
    "get_pr_status",
    "_get_open_prs",
    "update_hub_refs",
    "update_hub_refs_after_merge",
    "_analyze_remote_changes",
    "_classify_rebase_conflict",
    "check_ref_fast_forward",
    "_get_conflicting_submodule_refs",
    "_resolve_submodule_ref_conflict",
    "set_deploy_branch",
    "is_project_blocked_by_changeset",
    "get_changeset_context",
]

#: Deliberately kept, because these have live callers.
KEPT_NAMES = [
    "log_ref_update",
]

#: Removed later, by US-PM-35-8, when the git-status dashboard stopped scoring
#: deploy-branch alignment and started reading each subproject's *store*
#: through ``worktree.store_git_state``.  Listed apart from the sixteen so the
#: history stays readable: these two were the last readers of the
#: ``deploy_branch`` config key from the hub side.
REMOVED_LATER = [
    "_get_deploy_branch",
    "_get_tracking_branch",
]

#: Fragments a PR workflow leaves in source even after the functions go.
FORBIDDEN_SOURCE_PATTERNS = [
    r"gh\s+pr\b",
    r"pull\s*request",
    r"pull_request",
    r"auto[-_ ]?resolv",
    r"resolv\w*[^.\n]{0,40}submodule",
    r"submodule[^.\n]{0,40}resolv",
]

#: Workflow names no tool and no command may carry, in either spelling.
FORBIDDEN_COMMAND_FRAGMENTS = [
    "feature-branch",
    "feature_branch",
    "create-pr",
    "create_pr",
    "pr-status",
    "pr_status",
    "deploy-branch",
    "deploy_branch",
]


def _registry_source() -> str:
    """The text of the real ``hub/registry.py`` on disk."""
    return Path(registry.__file__).read_text(encoding="utf-8")


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


@pytest.fixture
def every_family_registered():
    """Run the body with all gated tool families on, and restore what was there.

    Gating removes tools from the registry, so a check run under the ambient
    configuration cannot tell "deleted" from "currently hidden".
    """
    before = gated_tool_state()
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    try:
        yield
    finally:
        apply_tool_gating(before)


# ------------------------------------------------- (1) the names are gone --


@pytest.mark.parametrize("name", REMOVED_NAMES)
def test_the_removed_function_is_not_an_attribute_of_the_registry(name):
    assert not hasattr(registry, name), (
        f"projectman.hub.registry still exposes {name!r}"
    )


@pytest.mark.parametrize("name", REMOVED_LATER)
def test_the_deploy_branch_readers_went_with_the_alignment_scoring(name):
    """US-PM-35-8: nothing hub-side reads a subproject's deploy branch now."""
    assert not hasattr(registry, name), (
        f"projectman.hub.registry still exposes {name!r} — the git-status "
        f"dashboard reads each subproject's store, not its deploy branch"
    )


@pytest.mark.parametrize("name", KEPT_NAMES)
def test_the_kept_function_survived_the_removal(name):
    """A control, and a guard: over-deleting must fail here, not at a caller."""
    assert callable(getattr(registry, name, None)), (
        f"projectman.hub.registry lost {name!r}, which still has callers"
    )


def test_the_removed_names_do_not_appear_in_the_module_source_either():
    """Not even as a stale comment, docstring, or commented-out definition."""
    source = _registry_source()
    offenders = sorted(name for name in REMOVED_NAMES if name in source)
    assert offenders == [], f"hub/registry.py still mentions {offenders}"


# ------------------------------------------- (2) no PR / auto-resolve prose --


@pytest.mark.parametrize("pattern", FORBIDDEN_SOURCE_PATTERNS)
def test_the_registry_source_has_no_pr_or_auto_resolution_wording(pattern):
    source = _registry_source()
    hits = [
        (source[: match.start()].count("\n") + 1, match.group(0))
        for match in re.finditer(pattern, source, re.IGNORECASE)
    ]
    assert hits == [], f"hub/registry.py matches {pattern!r} at {hits}"


def test_the_source_scan_reads_the_real_module():
    """A control: the scanned text must be the registry, not an empty read."""
    source = _registry_source()
    assert "def log_ref_update(" in source
    assert len(source) > 10_000


# ------------------------------------ (3) no tool and no command is named for it --


def test_no_registered_mcp_tool_is_named_for_the_pr_workflow(every_family_registered):
    names = _registered_tool_names()
    offenders = sorted(
        name
        for name in names
        if any(fragment in name.lower() for fragment in FORBIDDEN_COMMAND_FRAGMENTS)
    )
    assert offenders == [], f"tools/list still serves {offenders}"
    # The registry is otherwise populated, so an empty list cannot pass this.
    assert "pm_grab" in names


def test_no_gated_tool_family_names_a_pr_workflow_tool():
    for family, tools in TOOL_FAMILIES.items():
        offenders = sorted(
            tool
            for tool in tools
            if any(f in tool.lower() for f in FORBIDDEN_COMMAND_FRAGMENTS)
        )
        assert offenders == [], f"family {family!r} still names {offenders}"


def test_no_cli_command_is_named_for_the_pr_workflow():
    from projectman.cli import cli

    paths = _command_paths(cli)
    offenders = sorted(
        "/".join(path)
        for path in paths
        if any(
            fragment in segment.lower()
            for segment in path
            for fragment in FORBIDDEN_COMMAND_FRAGMENTS
        )
    )
    assert offenders == [], f"the CLI still registers {offenders}"
    # The walk found real commands, so an empty tree cannot pass this.
    assert any("status" in path[0] for path in paths), sorted(paths)
