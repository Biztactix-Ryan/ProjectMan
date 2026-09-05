"""US-PM-27-4 — the docs no longer describe changesets or the hub PR workflow.

US-PM-27's acceptance criterion: "Hub docs no longer describe changesets or the
PR workflow". The docs sweep (US-PM-27-8) is a one-off edit; this module is the
part that keeps it swept, so a later doc edit cannot quietly re-document a
feature that no longer exists.

Five checks, all against the real artefacts rather than a memory of them:

1. **No line in the prose names a removed symbol.** Every identifier the
   subtraction deleted — the ``pm_changeset_*`` tools, the ``projectman
   changeset`` CLI group and ``changeset-status``, ``next_changeset_id``,
   ``.project/changesets``, ``create_pr`` / ``get_pr_status``,
   ``update_hub_refs``, ``create_feature_branch``, ``set_deploy_branch``, and
   the *automatic* submodule-ref resolution inside ``hub_push_with_rebase`` —
   is searched for over ``docs/**/*.md`` and ``README.md``.
2. **The word "changeset" survives only in the past tense.** A handful of
   historical notes legitimately record that the feature existed and was taken
   out; anything that still *explains how to use it* would not carry a
   removal marker, and is caught here.
3. **``docs/reference/mcp-tools.md`` matches the server exactly** — every
   ``### pm_<name>`` heading names a registered tool, and every registered tool
   has a heading. Asserted over a real ``tools/list`` with *all* gated families
   switched on, so a tool merely hidden by the ambient config is not mistaken
   for a deleted one, and a heading for a deleted tool cannot hide behind
   gating either.
4. **``docs/reference/cli.md`` documents no command the click CLI lacks** —
   walked over the real command tree, groups included.
5. **``CHANGELOG.md`` still records the removal**, so the trail back to *why*
   these things are absent is not itself swept away.

Scope note: ``docs/telemetry/`` is excluded from checks 1 and 2. Those files are
recorded measurements of a past state, not instructions, and rewriting them
would falsify the baselines. ``CHANGELOG.md`` is likewise outside checks 1 and 2
— check 5 exists precisely because the changelog *must* mention the removed
names.

This module only ever reads the repository; nothing here writes to ``docs/``,
``README.md``, ``CHANGELOG.md`` or ``.project/``.
"""

import re
from pathlib import Path

import anyio
import pytest
import click
from mcp import types

from projectman.cli import cli
from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp as mcp_server,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
MCP_TOOLS_DOC = DOCS / "reference" / "mcp-tools.md"
CLI_DOC = DOCS / "reference" / "cli.md"

#: Recorded measurements of a past state — historical data, deliberately unswept.
EXCLUDED_DIRS = {DOCS / "telemetry"}

#: Symbols the subtraction deleted. Plain substrings unless noted; matched
#: case-insensitively against one line at a time.
FORBIDDEN = [
    r"pm_changeset",
    r"projectman\s+changeset",
    r"changeset-status",
    r"next_changeset_id",
    r"\.project/changesets",
    r"create_pr",
    r"get_pr_status",
    r"update_hub_refs",
    r"create_feature_branch",
    r"set_deploy_branch",
    # ``hub_push_with_rebase`` itself survived — fetch, rebase, push again is
    # still how a rejected hub push is retried. What went is the part that
    # resolved a submodule-ref conflict *automatically* instead of aborting and
    # reporting, so only the pairing of the function with "auto" is forbidden.
    r"hub_push_with_rebase.*auto|auto.*hub_push_with_rebase",
]

FORBIDDEN_RES = [re.compile(pattern, re.IGNORECASE) for pattern in FORBIDDEN]

#: A mention may survive if its paragraph says so in the past tense. The unit is
#: the paragraph rather than the physical line because these docs are hard
#: wrapped at 80 columns: "…a named changeset was built under / US-PRJ-10 and
#: **removed again under US-PM-27**…" is one sentence split across two lines,
#: and a per-line rule would flag its first half while its second half carries
#: the marker. ``test_marker_rule_rejects_a_live_description`` pins that this
#: stays a granularity choice and not a hole.
REMOVAL_MARKERS = ("removed", "dropped", "no longer", "built, then removed")

CHANGESET_RE = re.compile(r"changeset", re.IGNORECASE)

#: ``### pm_status(project?)`` → ``pm_status``
TOOL_HEADING_RE = re.compile(r"^###\s+(pm_[a-z0-9_]+)", re.MULTILINE)

#: ``## projectman set-branch`` → ``set-branch``. Anchored so prose headings
#: that merely contain the word (``## Living with the projectman worktree``)
#: are not read as command documentation.
CLI_HEADING_RE = re.compile(r"^##\s+projectman\s+([a-z0-9][a-z0-9-]*)", re.MULTILINE)


# ─── Helpers ──────────────────────────────────────────────────────


def _swept_files() -> list[Path]:
    """Every markdown file the criterion covers: docs/ (less telemetry) + README."""
    files = [
        path
        for path in sorted(DOCS.rglob("*.md"))
        if not any(excluded in path.parents for excluded in EXCLUDED_DIRS)
    ]
    files.append(README)
    return files


def _swept_lines():
    """Yield ``(relative path, 1-based line number, text)`` over the swept files."""
    for path in _swept_files():
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            yield path.relative_to(REPO_ROOT), number, line


def _changeset_offenders(text: str):
    """Yield ``(line number, line)`` for "changeset" mentions in a live context.

    A mention is an offender when the *paragraph* around it — the run of
    consecutive non-blank lines it sits in — carries no removal marker.
    """
    lines = text.splitlines()
    start = 0
    while start < len(lines):
        if not lines[start].strip():
            start += 1
            continue
        end = start
        while end < len(lines) and lines[end].strip():
            end += 1
        block = "\n".join(lines[start:end]).lower()
        if not any(marker in block for marker in REMOVAL_MARKERS):
            for offset, line in enumerate(lines[start:end], start=start + 1):
                if CHANGESET_RE.search(line):
                    yield offset, line
        start = end


def _cite(offenders) -> str:
    """Render offending lines as ``file:line`` citations, one per line."""
    return "\n".join(
        f"  {path}:{number}: {line.strip()}" for path, number, line in offenders
    )


def _command_names(command, seen=None) -> set:
    """Every command name in the click tree, at any nesting depth."""
    seen = set() if seen is None else seen
    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            seen.add(name)
            _command_names(sub, seen)
    return seen


@pytest.fixture
def every_family_registered():
    """Run the body with all gated families on, and restore what was there.

    Gating removes tools from the registry, so a comparison run under the
    ambient ``.project/config.yaml`` could not tell "deleted" from "currently
    hidden" in either direction.
    """
    before = gated_tool_state()
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    try:
        yield
    finally:
        apply_tool_gating(before)


def _registered_tool_names() -> set:
    """The names in a real low-level ``tools/list`` response."""
    handler = mcp_server._mcp_server.request_handlers[types.ListToolsRequest]

    async def run():
        return (await handler(types.ListToolsRequest(method="tools/list"))).root

    return {tool.name for tool in anyio.run(run).tools}


# ─── 1. No removed symbol is named anywhere in the prose ──────────


def test_swept_files_exist():
    """A typo in the paths above must not make the sweep vacuously pass."""
    files = _swept_files()
    assert README in files, "README.md is not in the swept set"
    assert MCP_TOOLS_DOC in files, f"{MCP_TOOLS_DOC} is not in the swept set"
    assert len(files) > 10, f"only {len(files)} markdown files found under {DOCS}"
    assert all(path.exists() for path in files)


@pytest.mark.parametrize("pattern", FORBIDDEN, ids=lambda p: p[:40])
def test_no_removed_symbol_in_docs(pattern):
    """No swept line names a symbol the subtraction deleted."""
    matcher = re.compile(pattern, re.IGNORECASE)
    offenders = [
        (path, number, line)
        for path, number, line in _swept_lines()
        if matcher.search(line)
    ]
    assert not offenders, (
        f"{len(offenders)} line(s) still document the removed "
        f"`{pattern}`:\n{_cite(offenders)}\n"
        "US-PM-27 deleted it; the docs must not describe it as available."
    )


# ─── 2. "changeset" only ever appears in the past tense ───────────


def test_changeset_mentioned_only_as_removed():
    """Every surviving "changeset" mention records the removal, not the feature."""
    offenders = [
        (path.relative_to(REPO_ROOT), number, line)
        for path in _swept_files()
        for number, line in _changeset_offenders(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"{len(offenders)} line(s) mention changesets without saying they were "
        f"removed:\n{_cite(offenders)}\n"
        "A historical note's paragraph must carry one of "
        f"{list(REMOVAL_MARKERS)}; anything else reads as a description of a "
        "feature that no longer exists."
    )


def test_marker_rule_rejects_a_live_description():
    """The paragraph rule still catches prose that documents changesets as usable.

    Guards the granularity choice above: widening from line to paragraph must
    not turn the check into one that passes on anything.
    """
    live = "Run `pm_changeset_create` to open a changeset across repos.\n"
    assert list(_changeset_offenders(live)) == [(1, live.rstrip("\n"))]

    # …and a neighbouring paragraph's marker does not launder it.
    two_paragraphs = "The changeset feature was removed.\n\n" + live
    assert [number for number, _ in _changeset_offenders(two_paragraphs)] == [3]

    # A genuine historical note passes, wrapped across lines or not.
    wrapped = "A named changeset was built under\nUS-PRJ-10 and removed under US-PM-27.\n"
    assert list(_changeset_offenders(wrapped)) == []


# ─── 3. The MCP tool reference matches the server exactly ─────────


def test_mcp_tools_doc_matches_tools_list(every_family_registered):
    """Every ``### pm_*`` heading is a real tool, and every real tool is documented."""
    documented = set(TOOL_HEADING_RE.findall(MCP_TOOLS_DOC.read_text(encoding="utf-8")))
    registered = _registered_tool_names()

    assert documented, f"no `### pm_<name>` headings found in {MCP_TOOLS_DOC}"

    phantom = sorted(documented - registered)
    assert not phantom, (
        f"{MCP_TOOLS_DOC.relative_to(REPO_ROOT)} documents "
        f"{len(phantom)} tool(s) the server does not register "
        f"(all gated families on): {phantom}"
    )

    undocumented = sorted(registered - documented)
    assert not undocumented, (
        f"{len(undocumented)} registered tool(s) have no `### ` heading in "
        f"{MCP_TOOLS_DOC.relative_to(REPO_ROOT)}: {undocumented}"
    )


# ─── 4. The CLI reference documents no command the CLI lacks ──────


def test_cli_doc_documents_no_absent_command():
    """Every ``## projectman <cmd>`` heading names a command click still has."""
    documented = set(CLI_HEADING_RE.findall(CLI_DOC.read_text(encoding="utf-8")))
    available = _command_names(cli)

    assert documented, f"no `## projectman <cmd>` headings found in {CLI_DOC}"

    phantom = sorted(documented - available)
    assert not phantom, (
        f"{CLI_DOC.relative_to(REPO_ROOT)} documents {len(phantom)} command(s) "
        f"the click CLI does not define: {phantom}"
    )


# ─── 5. The changelog still records why all of this is absent ─────


def test_changelog_unreleased_records_the_removal():
    """``## [Unreleased]`` carries a ``### Removed`` heading mentioning changesets."""
    text = CHANGELOG.read_text(encoding="utf-8")

    start = re.search(r"^##\s+\[Unreleased\]", text, re.MULTILINE)
    assert start, "CHANGELOG.md has no `## [Unreleased]` section"

    following = re.search(r"^##\s+(?!#)", text[start.end() :], re.MULTILINE)
    section = text[start.end() : start.end() + following.start()] if following else text[start.end() :]

    removed = re.search(r"^###\s+Removed\s*$", section, re.MULTILINE)
    assert removed, (
        "CHANGELOG.md's `## [Unreleased]` section has no `### Removed` heading — "
        "US-PM-27 took a documented feature out and the changelog must say so."
    )

    nxt = re.search(r"^###\s+", section[removed.end() :], re.MULTILINE)
    body = (
        section[removed.end() : removed.end() + nxt.start()]
        if nxt
        else section[removed.end() :]
    )
    assert CHANGESET_RE.search(body), (
        "the `### Removed` entry under `## [Unreleased]` does not mention "
        "changesets; the only surviving record of the subtraction is gone."
    )
