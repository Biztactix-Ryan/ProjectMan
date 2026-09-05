"""US-PM-23-1 / US-PM-23-2 — the ``## Upgrading`` section of docs/installation.md.

Two of US-PM-23's acceptance criteria are pinned here, both over the *same*
slice of ``docs/installation.md`` — the text from ``## Upgrading`` down to the
next top-level ``##`` heading:

* "docs/installation.md has an Upgrading section with the pipx force-reinstall
  from a local path and the refresh-skills step" (US-PM-23-1)
* "The Upgrading section names the symptom of a stale install and the mcp<2
  requirement" (US-PM-23-2)

The point of the section is that a reader following it ends up with a pipx
install that matches their checkout. That only holds while the commands in the
prose are commands the code actually accepts, so the facts are read back out of
the code rather than hard-coded here:

* the extras key in ``pipx install --force "<path>[<extras>]"`` is looked up in
  ``pyproject.toml``'s ``[project.optional-dependencies]``;
* ``--keep-local`` is looked up in ``projectman.cli.refresh_skills.params``;
* the ``mcp`` pin is read from the ``mcp`` extra in ``pyproject.toml``;
* the "MCP extras not installed" error is read out of the source that emits it.

A doc edit that drifts from any of those fails here; so does a rename on the
code side that leaves the doc telling people to run something that no longer
exists.

This module only reads the repository — no store writes, no subprocesses.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_DOC = REPO_ROOT / "docs" / "installation.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
SRC = REPO_ROOT / "src" / "projectman"

#: Phrases pinned as "symptoms of a stale install" (case-insensitive). At least
#: two must appear, and "older version" is required — it is the one symptom that
#: describes the failure mode itself rather than one of its shapes.
SYMPTOM_PHRASES = ("older version", "rejected", "missing")

#: The doc must frame those symptoms as belonging to a *stale* install.
STALE_WORD = "stale"


# --------------------------------------------------------------------------- #
# Reading the artefacts
# --------------------------------------------------------------------------- #


def _upgrading_section() -> str:
    """The ``## Upgrading`` section, heading included, up to the next ``## ``.

    ``### `` subheadings stay inside the slice — ``"### x".startswith("## ")``
    is False — which is what keeps the ``mcp<2`` subsection in scope.
    """
    lines = INSTALL_DOC.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^##\s+Upgrading\s*$", line):
            start = i
            break
    assert start is not None, (
        f"{INSTALL_DOC.relative_to(REPO_ROOT)} has no `## Upgrading` heading, so "
        "there is no upgrade path documented at all."
    )
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


SECTION = _upgrading_section()
#: Prose with line wrapping collapsed, so an assertion is not defeated by a
#: sentence that happens to break across two source lines.
FLAT = re.sub(r"\s+", " ", SECTION)


def _optional_dependencies() -> dict:
    """``[project.optional-dependencies]`` from pyproject, as {extra: [specs]}."""
    text = PYPROJECT.read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        tomllib = None
    if tomllib is not None:
        table = tomllib.loads(text).get("project", {}).get("optional-dependencies", {})
        assert table, "pyproject.toml declares no [project.optional-dependencies]"
        return table
    block = re.search(
        r"^\[project\.optional-dependencies\]\s*$(.*?)(?=^\[)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert block, "pyproject.toml declares no [project.optional-dependencies]"
    return {
        m.group(1): re.findall(r'"([^"]+)"', m.group(2))
        for m in re.finditer(r"^(\w[\w.-]*)\s*=\s*(\[[^\]]*\])", block.group(1), re.MULTILINE)
    }


def _fenced_blocks(info: str | None = None) -> list[str]:
    """Bodies of the section's fenced code blocks, optionally by info string."""
    out = []
    for m in re.finditer(r"^```([^\n]*)\n(.*?)^```", SECTION, re.MULTILINE | re.DOTALL):
        if info is None or m.group(1).strip() == info:
            out.append(m.group(2))
    return out


def _inline_code_spans() -> list[str]:
    """Every inline ``code`` span in the section's prose.

    Fenced blocks are removed first — their triple backticks would otherwise
    pair up with the prose's single ones — and the remainder is flattened, so a
    span broken across a wrapped line is still matched as one span.
    """
    prose = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", SECTION, flags=re.MULTILINE | re.DOTALL)
    return [span.strip() for span in re.findall(r"`([^`]+)`", re.sub(r"\s+", " ", prose))]


def _mcp_requirement() -> str:
    """The pyproject dependency string for mcp, e.g. ``mcp[cli]>=1.0,<2``."""
    for specs in _optional_dependencies().values():
        for spec in specs:
            if spec.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip() == "mcp":
                return spec
    raise AssertionError("pyproject.toml declares no `mcp` dependency to pin")


def _mcp_extras_error() -> str:
    """The 'MCP extras not installed' message, as the source actually emits it."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for m in re.finditer(
            r'"([^"\n]*MCP extras not installed[^"\n]*)"', path.read_text(encoding="utf-8")
        ):
            found.add(m.group(1))
    assert found, "no source file under src/projectman emits 'MCP extras not installed'"
    assert len(found) == 1, f"conflicting 'MCP extras not installed' messages in source: {found}"
    return found.pop()


# --------------------------------------------------------------------------- #
# US-PM-23-1 — the reinstall recipe
# --------------------------------------------------------------------------- #


def test_force_reinstall_from_a_local_path_with_a_real_extras_key():
    """A bash block runs `pipx install --force` against a local path + real extras."""
    blocks = _fenced_blocks("bash")
    assert blocks, "the Upgrading section has no ```bash fenced block"

    for body in blocks:
        m = re.search(
            r"pipx install --force\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))",
            body,
        )
        if m:
            break
    else:
        raise AssertionError(
            "no ```bash block in the Upgrading section runs `pipx install --force`; "
            "without --force pipx skips the reinstall when the version number has "
            "not changed, which is the whole failure mode this section exists for."
        )

    target = m.group(1) or m.group(2) or m.group(3)
    spec = re.match(r"^(?P<path>.+?)\[(?P<extras>[^\]]+)\]$", target)
    assert spec, (
        f"`pipx install --force {target}` names no extras; the MCP server needs "
        "the mcp extra, so the documented command must install one."
    )

    path, extras = spec.group("path"), spec.group("extras")
    assert "://" not in path, (
        f"`pipx install --force` targets {path!r}, a URL — the point of this "
        "section is reinstalling from the developer's own working tree."
    )
    assert "/" in path or path.startswith("."), (
        f"`pipx install --force` targets {path!r}, which does not read as a "
        "filesystem path; a bare name reinstalls from PyPI, not the checkout."
    )

    declared = _optional_dependencies()
    for key in (k.strip() for k in extras.split(",")):
        assert key in declared, (
            f"the documented install uses the extras key {key!r}, which is not in "
            f"pyproject.toml's [project.optional-dependencies] {sorted(declared)}; "
            "the command would fail or silently install nothing extra."
        )


def test_refresh_skills_step_uses_a_real_option():
    """The section runs `projectman refresh-skills --keep-local`, a real CLI option."""
    assert re.search(r"projectman refresh-skills --keep-local", FLAT), (
        "the Upgrading section never runs `projectman refresh-skills --keep-local`; "
        "reinstalling the package alone leaves the previously rendered pm skills "
        "in place, so the agent keeps reading stale instructions."
    )

    from projectman.cli import refresh_skills

    opts = {opt for param in refresh_skills.params for opt in getattr(param, "opts", ())}
    assert "--keep-local" in opts, (
        "docs tell the reader to run `refresh-skills --keep-local`, but the click "
        f"command exposes {sorted(opts)} — the documented command would abort."
    )


def test_plain_pipx_upgrade_is_called_out_as_insufficient():
    """The section says `pipx upgrade` does not pick up local changes."""
    assert re.search(
        r"pipx upgrade[^.]*\b(?:never|not|does not|doesn't|will not|won't)\b[^.]*local changes",
        FLAT,
    ), (
        "the Upgrading section does not say that a plain `pipx upgrade` fails to "
        "pick up local changes; a reader who reaches for the obvious command gets "
        "a no-op and concludes the install is current."
    )


def test_reader_is_told_to_restart_claude_code():
    """The section says to restart Claude Code once the reinstall is done."""
    assert re.search(r"restart\s+Claude\s+Code", FLAT, re.IGNORECASE), (
        "the Upgrading section never tells the reader to restart Claude Code; the "
        "MCP server is a long-lived child process, so the running session keeps "
        "the old code and the upgrade looks like it did nothing."
    )


def test_section_stays_short():
    """The section is under 40 lines — a checklist someone will actually read."""
    length = len(SECTION.splitlines())
    assert length < 40, (
        f"the Upgrading section is {length} lines; it is meant to be a short "
        "recipe, and anything longer stops being scannable mid-incident."
    )


# --------------------------------------------------------------------------- #
# US-PM-23-2 — stale-install symptoms and the mcp<2 requirement
# --------------------------------------------------------------------------- #


def test_names_at_least_two_stale_install_symptoms():
    """The section describes how a stale install *presents*, not just how to fix it."""
    flat = FLAT.lower()
    assert STALE_WORD in flat, (
        "the Upgrading section never uses the word 'stale', so nothing connects "
        "the symptoms it lists to an out-of-date install."
    )
    present = [p for p in SYMPTOM_PHRASES if p in flat]
    assert "older version" in present, (
        "the Upgrading section never says the install behaves like an 'older "
        f"version'; pinned symptom phrases are {list(SYMPTOM_PHRASES)}, found "
        f"{present}."
    )
    assert len(present) >= 2, (
        "the Upgrading section names fewer than two stale-install symptoms "
        f"(pinned phrases {list(SYMPTOM_PHRASES)}, found {present}); one symptom "
        "is not enough for a reader to recognise their own failure in it."
    )


def test_states_the_mcp_pin_as_pyproject_declares_it():
    """The `<2` bound is quoted in the section, exactly as pyproject declares it."""
    requirement = _mcp_requirement()
    assert "<2" in requirement, (
        f"pyproject declares mcp as {requirement!r} with no `<2` upper bound — the "
        "doc and this test are pinning a constraint the package no longer has."
    )

    def squeeze(s: str) -> str:
        return re.sub(r"\s+", "", s)

    spans = _inline_code_spans()
    assert any(squeeze(requirement) in squeeze(span) for span in spans), (
        f"the Upgrading section never quotes the mcp requirement {requirement!r} "
        f"as pyproject declares it; quoted code spans are {spans}."
    )
    assert any("<2" in span for span in spans), (
        "the Upgrading section mentions no `<2` bound in code formatting, so the "
        "constraint a reader must reproduce by hand is not copyable."
    )


def test_quotes_the_mcp_extras_error_verbatim():
    """The failure text a stale env prints is quoted exactly as the source emits it."""
    message = _mcp_extras_error()
    assert message in SECTION, (
        f"the Upgrading section does not quote the error {message!r} verbatim; a "
        "reader searching the web or the docs for the string their terminal just "
        "printed would not land here."
    )
    assert any(message in body for body in _fenced_blocks()), (
        f"the error {message!r} appears in the Upgrading section but not inside a "
        "fenced block, so prose wrapping can corrupt the string a reader matches "
        "against their own output."
    )
