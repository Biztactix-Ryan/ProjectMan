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
   these things are absent is not itself swept away. Read out of the newest
   *versioned* section, since cutting a release moves the record out of
   ``Unreleased`` and into the version it shipped in.

US-PM-37-5 added three more of the same shape, for the *second* subtraction —
EPIC-PM-5's hub redesign:

6. **No doc names the removed hub surface** — ``.project/projects``, the
   coordinated push, the repair command or the branch-alignment check — and no
   doc gives a ``pm_`` tool a ``project`` argument. ``docs/telemetry/`` is
   excluded, as is any page carrying the history marker (see below).
7. **``.project/DECISIONS.md`` records ADR-003**, with its Alternatives section,
   and the ADRs stay in the file's stated newest-first order.

US-PM-47-5 added the third and last of these, for EPIC-PM-6 — the removal of
hub mode itself (ADR-004):

8. **No page describes hub mode at all.** The sweep is the strongest of the
   three: it runs over ``docs/`` (telemetry included — those files are hub-free),
   ``README.md`` *and* ``src/projectman/templates``, and it forbids the mode by
   name (``hub mode``, ``hub-mode``), its CLI verbs (``migrate-hub``,
   ``add-project``, ``set-branch``), its store layout
   (``projects/{name}/.project``) and the ``prefix`` *argument* that used to
   address a store — while leaving the ID prefix alone, since ADR-004 keeps it
   (``US-PREFIX-N``, ``prefix: PRJ``, ``projectman init --prefix``).

   ``CHANGELOG.md`` and ``.project/DECISIONS.md`` are outside the swept set:
   both exist to record that hub mode was here and is gone. A reference document
   that must keep naming hub internals earns its exemption by carrying a
   **history marker** — a blockquote under its H1 saying hub mode has been
   removed and that what follows is a record. The exemption is by marker and
   never by filename, so a page written tomorrow gets it the same way and a page
   that drops the marker loses it in the same commit;
   ``test_hub_sweep_rejects_an_unmarked_page`` pins that this stays a rule about
   the page and not a hole in the sweep.

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


#: ``## [0.9.0] - 2026-09-08`` → ``0.9.0``; ``## [Unreleased]`` does not match.
VERSION_HEADING_RE = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def _changelog_section(text: str, heading: re.Match) -> str:
    """The body under *heading*, down to the next ``## `` heading."""
    following = re.search(r"^##\s+(?!#)", text[heading.end() :], re.MULTILINE)
    if following:
        return text[heading.end() : heading.end() + following.start()]
    return text[heading.end() :]


def test_changelog_records_the_removal_in_a_released_section():
    """Some *released* section carries a ``### Removed`` naming changesets.

    US-PM-42-7 cut ``## [Unreleased]`` as ``## [0.9.0]`` and opened a fresh,
    empty ``Unreleased`` above it, which is where the subtraction's record went
    with it. Later releases stack above 0.9.0, so the check follows the content
    rather than position: at least one *versioned* section must still explain
    why changesets are absent. A fresh ``Unreleased`` is expected to be empty
    and is deliberately not searched — asserting against it would have made
    this pass on a changelog that had lost the record entirely.
    """
    text = CHANGELOG.read_text(encoding="utf-8")

    assert re.search(r"^##\s+\[Unreleased\]", text, re.MULTILINE), (
        "CHANGELOG.md has no `## [Unreleased]` heading — Keep a Changelog keeps "
        "one open above the newest release for what has landed since it."
    )

    releases = list(VERSION_HEADING_RE.finditer(text))
    assert releases, "CHANGELOG.md has no `## [X.Y.Z]` release section at all"

    for release in releases:
        section = _changelog_section(text, release)
        removed = re.search(r"^###\s+Removed\s*$", section, re.MULTILINE)
        if not removed:
            continue
        nxt = re.search(r"^###\s+", section[removed.end() :], re.MULTILINE)
        body = (
            section[removed.end() : removed.end() + nxt.start()]
            if nxt
            else section[removed.end() :]
        )
        if CHANGESET_RE.search(body):
            return

    versions = ", ".join(r.group(1) for r in releases)
    raise AssertionError(
        f"no `### Removed` entry under any released section ({versions}) "
        "mentions changesets; the only surviving record of the subtraction "
        "is gone."
    )


# ─── 6. US-PM-37-5 — the hub redesign's removed surface is swept too ─────
#
# EPIC-PM-5 removed a second family of things the docs used to describe: the
# optional ``project`` argument on every tool (US-PM-34), the hub's per-project
# store directory ``.project/projects/{name}`` (US-PM-31), and the cross-repo
# git verbs — the coordinated push, the repair command and the branch-alignment
# check (US-PM-35). The sweep in US-PM-37-5 is a one-off edit; these two checks
# keep it swept, in the same shape as checks 1 and 5 above.

#: A page may still name retired hub machinery if it declares itself history in
#: its preamble — a blockquote immediately under the H1 saying hub mode has been
#: removed and that what follows is a record, not a description of the package.
#: Matched as a *marker*, never as a filename: a future page that earns the same
#: exemption gets it by carrying the marker, and a page that loses the marker
#: loses the exemption in the same commit.
#:
#: ``docs/hub-mode/setup.md`` used to hold this exemption by name, with an
#: ``## History`` heading; US-PM-47-4 deleted the whole directory, so the rule
#: moved to the marker and the filename left the test.
HISTORY_MARKER_RE = re.compile(
    r"^>\s*\*\*History\s*\([^)]*\):\*\*[^\n]*\bhub mode has been\b[^\n]*\bremoved\b",
    re.IGNORECASE | re.MULTILINE,
)

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
#: bare ``project=``: the web layer routes by prefix as of US-PM-39, so no live
#: surface takes a project name any more, but ``src/projectman/web/resolve.py``
#: and this file's own history explain the removed ``?project=`` parameter in
#: prose, and a doc naming it *as retired* is not an offender.
TOOL_PROJECT_ARG_RE = re.compile(r"pm_[a-z_]+\([^)]*\bproject\s*[=?]")


def _is_history_marked(text: str) -> bool:
    """True when the page's *preamble* declares it a historical record.

    The marker only counts above the first ``##`` heading. A blockquote buried
    in a later section describes that section, not the page, and must not
    launder live prose sitting above it — ``test_hub_sweep_rejects_an_unmarked_page``
    pins that.
    """
    preamble = re.split(r"^##\s", text, maxsplit=1, flags=re.MULTILINE)[0]
    return bool(HISTORY_MARKER_RE.search(preamble))


def test_no_doc_describes_the_removed_hub_surface():
    """No swept line names a symbol EPIC-PM-5 removed.

    Excludes ``docs/telemetry/`` (recorded measurements) and any page carrying
    the history marker, which may name retired commands as retired.
    """
    offenders = []
    for path in _swept_files():
        text = path.read_text(encoding="utf-8")
        if _is_history_marked(text):
            continue
        relative = path.relative_to(REPO_ROOT)
        for number, line in enumerate(text.splitlines(), start=1):
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
    """The ADRs run newest first: ADR-004 above ADR-003 above ADR-002.

    ADR-004 (US-PM-47-5) records hub mode's removal and supersedes ADR-003, so
    the file's stated order now has three entries to keep straight.
    """
    text = DECISIONS.read_text(encoding="utf-8")
    positions = {}
    for number in ("004", "003", "002"):
        found = text.find(f"## ADR-{number}:")
        assert found != -1, f"DECISIONS.md is missing ADR-{number}"
        positions[number] = found

    assert positions["004"] < positions["003"] < positions["002"], (
        "DECISIONS.md says 'Newest first' but the ADRs are out of order: "
        f"{sorted(positions, key=positions.get)}"
    )


# ─── 8. US-PM-47-5 — no page describes hub mode at all ─────
#
# EPIC-PM-6 removed hub mode outright (ADR-004). Check 6 above sweeps the
# symbols EPIC-PM-5's *redesign* dropped; this is the stronger sweep that
# followed it — the mode itself, its CLI verbs, its store layout and the
# ``prefix`` argument that addressed a store — over a wider set of files:
# docs/ (telemetry included, it is hub-free), README.md and the Jinja templates
# the pm agent and skills are generated from.
#
# ``CHANGELOG.md`` and ``.project/DECISIONS.md`` are outside the swept set by
# construction: both exist to record that hub mode was there and is gone.
# History-marked pages are exempted by their marker, never by name.

TEMPLATES = REPO_ROOT / "src" / "projectman" / "templates"

#: ``pm_next(prefix="API")`` / ``**prefix**`` in a parameter table — a tool
#: argument naming a store. Deliberately narrow: the *ID* prefix survives ADR-004
#: (decision 2), so ``US-PREFIX-N``, ``prefix: PRJ`` in config.yaml and
#: ``projectman init --prefix APP`` are all live surface and must not match.
#: The lookbehind is what keeps ``--prefix=APP`` out.
PREFIX_ARG_RE = re.compile(r"(?<![-\w])prefix\s*[=?](?!=)", re.IGNORECASE)
PREFIX_BOLD_RE = re.compile(r"\*\*prefix\*\*", re.IGNORECASE)

#: Everything a page may no longer say, with the reason it may not say it.
HUB_FORBIDDEN = [
    (re.compile(r"hub[\s\-]mode", re.IGNORECASE), "hub mode / hub-mode"),
    (re.compile(r"migrate-hub", re.IGNORECASE), "the migrate-hub command"),
    (re.compile(r"add-project", re.IGNORECASE), "the add-project command"),
    (re.compile(r"set-branch", re.IGNORECASE), "the set-branch command"),
    (
        re.compile(r"projects/\{name\}/\.project", re.IGNORECASE),
        "the hub's per-project store layout",
    ),
    (PREFIX_ARG_RE, "a `prefix` argument on a tool"),
    (PREFIX_BOLD_RE, "a `prefix` argument on a tool"),
]


def _hub_swept_files() -> list[Path]:
    """docs/ + README.md + every template file the generator renders."""
    files = sorted(DOCS.rglob("*.md"))
    files.append(README)
    files.extend(sorted(path for path in TEMPLATES.rglob("*") if path.is_file()))
    return files


def _hub_offenders(text: str):
    """Yield ``(line number, line, reason)`` unless the page is marked history."""
    if _is_history_marked(text):
        return
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern, reason in HUB_FORBIDDEN:
            if pattern.search(line):
                yield number, line, reason
                break


def test_hub_sweep_covers_docs_readme_and_templates():
    """The swept set is the real one — and excludes the two history records."""
    files = _hub_swept_files()
    assert README in files, "README.md is not in the hub sweep"
    assert TEMPLATES / "skill_pm.md.j2" in files, "the skill template is not swept"
    assert TEMPLATES / "agent_pm.md.j2" in files, "the pm agent template is not swept"
    assert TEMPLATES / "config.yaml.j2" in files, "the config template is not swept"
    assert len(files) > 25, f"only {len(files)} files in the hub sweep"
    assert all(path.exists() for path in files)

    assert CHANGELOG not in files, "CHANGELOG.md records the removal and is exempt"
    assert DECISIONS not in files, "DECISIONS.md records the removal and is exempt"


def test_no_page_describes_hub_mode():
    """No doc, README line or template mentions hub mode or its removed surface.

    Exempt: ``CHANGELOG.md`` and ``.project/DECISIONS.md`` (outside the swept
    set — they record the removal), and any page whose preamble carries the
    history marker.
    """
    offenders = []
    for path in _hub_swept_files():
        relative = path.relative_to(REPO_ROOT)
        text = path.read_text(encoding="utf-8")
        for number, line, reason in _hub_offenders(text):
            offenders.append(f"  {relative}:{number}: {line.strip()}   [{reason}]")

    assert not offenders, (
        f"hub mode was removed in EPIC-PM-6 (ADR-004), but {len(offenders)} "
        "line(s) still describe it:\n" + "\n".join(offenders) + "\n"
        "A page that must name it as history needs the marker blockquote under "
        "its H1; anything else reads as a description of a mode the package "
        "does not have."
    )


def test_hub_sweep_rejects_an_unmarked_page():
    """The marker exemption is a rule about the page, not a hole in the sweep."""
    live = "# Setup\n\nRun `projectman add-project` to attach a repo in hub mode.\n"
    assert [number for number, _, _ in _hub_offenders(live)] == [3]

    marked = (
        "# Setup\n\n"
        "> **History (2026-09-08, EPIC-PM-6):** hub mode has been **removed**;\n"
        "> this page is kept as the record of what was there.\n\n"
        "Run `projectman add-project` to attach a repo in hub mode.\n"
    )
    assert list(_hub_offenders(marked)) == []

    # A marker under a later heading describes that section, not the page above it.
    late = (
        "# Setup\n\n"
        "Run `projectman add-project` to attach a repo in hub mode.\n\n"
        "## History\n\n"
        "> **History (2026-09-08, EPIC-PM-6):** hub mode has been **removed**.\n"
    )
    assert 3 in [number for number, _, _ in _hub_offenders(late)]

    # The ID prefix is live surface (ADR-004, decision 2) and must not be caught.
    keeps = (
        "# IDs\n\n"
        "Stories are `US-PREFIX-N`; run `projectman init --prefix APP` and\n"
        "`--prefix=APP` sets `prefix: APP` in config.yaml.\n"
    )
    assert list(_hub_offenders(keeps)) == []

    # …but a tool argument named `prefix` is not.
    tool_arg = '# Tools\n\nCall `pm_next(prefix="API")` for the API store.\n'
    assert [number for number, _, _ in _hub_offenders(tool_arg)] == [3]
