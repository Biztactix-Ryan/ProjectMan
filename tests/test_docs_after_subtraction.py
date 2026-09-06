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
   ``update_hub_refs``, ``create_feature_branch`` and ``set_deploy_branch`` —
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

US-PM-37-5 added three more of the same shape, for the *second* subtraction —
EPIC-PM-5's hub redesign:

6. **No doc names the removed hub surface** — ``.project/projects``, the
   coordinated push, the repair command or the branch-alignment check — and no
   doc gives a ``pm_`` tool a ``project`` argument. ``docs/telemetry/`` and the
   History section of ``docs/hub-mode/setup.md`` are excluded; the latter exists
   to name retired commands *as* retired.
7. **``.project/DECISIONS.md`` records ADR-003**, with its Alternatives section
   and above ADR-002, since ``docs/hub-mode/setup.md`` links at that anchor.

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


# ─── 6. US-PM-37-5 — the hub redesign's removed surface is swept too ─────
#
# EPIC-PM-5 removed a second family of things the docs used to describe: the
# optional ``project`` argument on every tool (US-PM-34), the hub's per-project
# store directory ``.project/projects/{name}`` (US-PM-31), and the cross-repo
# git verbs — the coordinated push, the repair command and the branch-alignment
# check (US-PM-35). The sweep in US-PM-37-5 is a one-off edit; these two checks
# keep it swept, in the same shape as checks 1 and 5 above.

#: The one place a retired hub command may still be named: ``setup.md``'s
#: History section exists precisely to explain commands found in old notes, and
#: names them *as retired*. Everything before that heading is live documentation
#: and is swept normally.
HUB_SETUP_DOC = DOCS / "hub-mode" / "setup.md"
HISTORY_HEADING_RE = re.compile(r"^##\s+History\b", re.MULTILINE)

#: Symbols and phrases EPIC-PM-5 removed. Matched case-insensitively, one line
#: at a time, over the same swept files as check 1.
REDESIGN_FORBIDDEN = [
    r"\.project/projects",
    r"push-all",
    r"validate-branches",
    r"pm_push_all",
    r"pm_repair",
    r"pm_validate_branches",
    r"coordinated\s+push",
]

REDESIGN_FORBIDDEN_RES = [
    re.compile(pattern, re.IGNORECASE) for pattern in REDESIGN_FORBIDDEN
]

#: ``pm_get("US-API-3", project="api")`` / ``pm_status(project?)`` — a
#: ``project`` argument in the same line as a ``pm_`` tool. Deliberately *not* a
#: bare ``project=``: ``src/projectman/web/routes/api.py`` still takes a
#: ``?project=`` HTTP query parameter, which is a route parameter and not a tool
#: argument, and a doc describing it accurately is not an offender.
TOOL_PROJECT_ARG_RE = re.compile(r"pm_[a-z_]+\([^)]*\bproject\s*[=?]")


def _history_line_span(path: Path) -> range:
    """1-based line numbers of ``setup.md``'s History section, else empty."""
    if path != HUB_SETUP_DOC:
        return range(0)
    text = path.read_text(encoding="utf-8")
    match = HISTORY_HEADING_RE.search(text)
    if not match:
        return range(0)
    first = text[: match.start()].count("\n") + 1
    return range(first, text.count("\n") + 2)


def test_no_doc_describes_the_removed_hub_surface():
    """No swept line names a symbol EPIC-PM-5 removed.

    Excludes ``docs/telemetry/`` (recorded measurements) and the History section
    of ``docs/hub-mode/setup.md``, which may name retired commands as retired.
    """
    history = {
        path: _history_line_span(path)
        for path in _swept_files()
        if path == HUB_SETUP_DOC
    }
    history_span = history.get(HUB_SETUP_DOC, range(0))

    offenders = []
    for relative, number, line in _swept_lines():
        if relative == HUB_SETUP_DOC.relative_to(REPO_ROOT) and number in history_span:
            continue
        for pattern in REDESIGN_FORBIDDEN_RES:
            if pattern.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
                break

    assert not offenders, (
        "EPIC-PM-5 removed the coordinated push, the repair command, the "
        "branch-alignment check and the hub's `.project/projects` layout, but "
        f"{len(offenders)} doc line(s) still name them:\n" + "\n".join(offenders)
    )


def test_no_doc_gives_a_pm_tool_a_project_argument():
    """US-PM-34 dropped ``project`` from every tool; the prefix names the store."""
    offenders = [
        f"{relative}:{number}: {line.strip()}"
        for relative, number, line in _swept_lines()
        if TOOL_PROJECT_ARG_RE.search(line)
    ]

    assert not offenders, (
        "no MCP tool takes a `project` argument since US-PM-34 — the ID prefix "
        "names the store, and ID-less verbs take an optional `prefix` — but "
        f"{len(offenders)} doc line(s) still show one:\n" + "\n".join(offenders)
    )


# ─── 7. US-PM-37-5 — ADR-003 records the redesign ─────

DECISIONS = REPO_ROOT / ".project" / "DECISIONS.md"

ADR3_HEADING = (
    "## ADR-003: PM data lives with its code — the hub is a read-only rollup "
    "(2026-09-06)"
)


def test_decisions_records_adr_003_with_its_alternatives():
    """``.project/DECISIONS.md`` carries ADR-003, with an Alternatives section.

    The heading text is pinned because ``docs/hub-mode/setup.md`` links into it,
    and the Alternatives section is pinned because an ADR that records only the
    decision loses the half that is worth keeping — why the other four designs
    lost.
    """
    assert DECISIONS.exists(), f"{DECISIONS} is missing"
    text = DECISIONS.read_text(encoding="utf-8")

    assert ADR3_HEADING in text, (
        "`.project/DECISIONS.md` has no ADR-003 heading reading exactly:\n"
        f"  {ADR3_HEADING}\n"
        "docs/hub-mode/setup.md links at that anchor."
    )

    start = text.index(ADR3_HEADING) + len(ADR3_HEADING)
    following = re.search(r"^##\s+ADR-", text[start:], re.MULTILINE)
    section = text[start : start + following.start()] if following else text[start:]

    assert re.search(r"\*\*Alternatives\b", section), (
        "ADR-003 has no **Alternatives** section — the designs that lost "
        "(hub-store per-project data, the sibling repo per project, an optional "
        "`project` argument beside the prefix, per-store epics with a hub "
        "index, an opt-in coordinated push) are the record's point."
    )

    for heading in ("**Status:**", "**Context.**", "**Decision.**", "**Consequences"):
        assert heading in section, f"ADR-003 is missing its {heading} section"


def test_adr_003_is_newest_first():
    """ADR-003 sits above ADR-002, keeping the file's stated newest-first order."""
    text = DECISIONS.read_text(encoding="utf-8")
    third = text.find("## ADR-003:")
    second = text.find("## ADR-002:")
    assert third != -1 and second != -1, "DECISIONS.md is missing ADR-002 or ADR-003"
    assert third < second, (
        "DECISIONS.md says 'Newest first' but ADR-003 was appended below ADR-002"
    )
