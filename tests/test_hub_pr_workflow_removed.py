"""US-PM-27-2 — the hub PR / ref-update / rebase-resolution workflow is gone.

US-PM-27's second acceptance criterion: "hub/registry.py no longer contains
feature-branch or PR or hub-ref-update or rebase-conflict code".

Pass 2 of the removal (US-PM-27-7) deleted sixteen functions from
``src/projectman/hub/registry.py``. Three things had to stay, because live
callers use them: :func:`hub_push_with_rebase` (reached by ``push_hub``),
:func:`log_ref_update` (reached by ``sync``), and the deploy-branch *check*
:func:`validate_not_on_deploy_branch` with its helper ``_get_deploy_branch``
(reached by ``push_preflight`` and ``git status``). So "the code is gone" is
not a whole-file grep — it is a claim about which names survived and, for the
one function that survived in stripped form, about what it now *does*.

This module pins four things:

1. none of the sixteen removed names is an attribute of the module — asserted
   against the imported module rather than its text, so a name that came back
   via a re-export would still be caught;
2. the module source carries no ``gh`` CLI pull-request invocation, no
   "pull request" wording, and no submodule-ref auto-resolution wording;
3. ``hub_push_with_rebase`` really is stripped: driven over a scripted
   ``subprocess.run``, a rebase conflict makes it run ``git rebase --abort``
   and report "manual resolution required" — it does not reach for submodule
   refs to fix the conflict itself;
4. no tool the MCP server registers and no click command is named for the
   feature-branch, create-pr, pr-status or deploy-branch workflow — the tool
   check runs with every gated family switched on, so a tool merely hidden
   behind a config flag would still be caught.

The functions that were *kept* are asserted present too (below), so a future
over-eager deletion fails here instead of at a caller.
"""

import re
import subprocess
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
    "hub_push_with_rebase",
    "log_ref_update",
    "validate_not_on_deploy_branch",
    "_get_deploy_branch",
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
    assert "def hub_push_with_rebase(" in source
    assert len(source) > 10_000


# ------------------------------- (3) a rebase conflict aborts, not resolves --


class _ScriptedGit:
    """Stand-in for ``subprocess.run`` that answers by git subcommand.

    Records every argv it is handed, so a test can assert *which* git commands
    ran — the point of this criterion is that ``rebase --abort`` runs and no
    submodule-ref surgery does.
    """

    def __init__(self, replies):
        #: {git subcommand: (returncode, stderr)}
        self.replies = replies
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        argv = list(args)
        self.calls.append(argv)
        for key, (code, stderr) in self.replies.items():
            if argv[1 : 1 + len(key.split())] == key.split():
                return subprocess.CompletedProcess(argv, code, stdout="", stderr=stderr)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def ran(self, key) -> bool:
        parts = key.split()
        return any(call[1 : 1 + len(parts)] == parts for call in self.calls)


_REJECTED = "! [rejected] main -> main (non-fast-forward)\nfailed to push some refs"


def test_a_rebase_conflict_aborts_and_asks_for_manual_resolution(
    tmp_hub, monkeypatch
):
    git = _ScriptedGit(
        {
            "push": (1, _REJECTED),
            "fetch": (0, ""),
            "rebase origin/main": (1, "CONFLICT (content): Merge conflict in a.txt"),
            "rebase --abort": (0, ""),
        }
    )
    monkeypatch.setattr(registry.subprocess, "run", git)

    result = registry.hub_push_with_rebase(root=tmp_hub)

    assert result["pushed"] is False
    assert "manual resolution" in (result["error"] or "").lower(), result
    assert git.ran("rebase --abort"), "the conflicted rebase was left in progress"
    # It must not try to fix the conflict by rewriting submodule refs.
    for call in git.calls:
        assert "submodule" not in call, f"unexpected submodule surgery: {call}"
        assert "checkout" not in call, f"unexpected checkout during conflict: {call}"


def test_the_scripted_git_can_also_produce_a_clean_push(tmp_hub, monkeypatch):
    """A control: the harness is capable of a passing push, so the failure
    above comes from the conflict script and not from a broken stand-in."""
    git = _ScriptedGit({"push": (0, "")})
    monkeypatch.setattr(registry.subprocess, "run", git)

    result = registry.hub_push_with_rebase(root=tmp_hub)

    assert result["pushed"] is True
    assert result["error"] is None
    assert not git.ran("rebase"), "a successful push must not rebase"


# ------------------------------------ (4) no tool and no command is named for it --


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
