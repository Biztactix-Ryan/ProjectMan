"""US-PM-57-5 — README and INFRASTRUCTURE.md describe the plugin install as the supported path.

US-PM-57's acceptance criterion: "README and INFRASTRUCTURE.md describe the
plugin install as the supported path". Pinned here:

* both docs name the two ``/plugin`` commands and ``projectman migrate-to-plugin``;
* README's Quick Start shows the plugin before any pipx or setup-claude step;
* neither doc presents ``setup-claude`` as the install path — every mention
  sits next to "deprecated" or the migration command, and no code block runs it.

The marketplace and plugin names come from ``.claude-plugin/marketplace.json``
and the GitHub slug from ``.claude-plugin/plugin.json``'s ``repository``, so a
rename moves the docs and this test together.

``.project/`` is a separate worktree checkout (the ``projectman`` branch) and
can be absent, e.g. in CI; the INFRASTRUCTURE.md tests skip with a reason then.

This module only reads the repository.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
INFRASTRUCTURE = REPO_ROOT / ".project" / "INFRASTRUCTURE.md"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN = REPO_ROOT / ".claude-plugin" / "plugin.json"

MIGRATE_CMD = "projectman migrate-to-plugin"


def _install_commands() -> tuple[str, str]:
    market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
    repo = plugin["repository"]
    slug = re.sub(r"^https://github\.com/", "", repo).rstrip("/")
    slug = re.sub(r"\.git$", "", slug)
    assert re.fullmatch(r"[^/\s]+/[^/\s]+", slug), f"unexpected repository {repo!r}"
    plugin_name = market["plugins"][0]["name"]
    return (
        f"/plugin marketplace add {slug}",
        f"/plugin install {plugin_name}@{market['name']}",
    )


def _infrastructure_text() -> str:
    if not INFRASTRUCTURE.is_file():
        pytest.skip(
            ".project/INFRASTRUCTURE.md is absent: .project is a separate worktree "
            "of the projectman branch and is not checked out here (e.g. CI)"
        )
    return INFRASTRUCTURE.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^(#+)\s+{re.escape(heading)}\s*$", text, re.MULTILINE
    )
    assert match, f"no `{heading}` heading"
    level = len(match.group(1))
    out, in_fence = [], False
    for line in text[match.end():].splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(rf"#{{1,{level}}}\s", line):
            break
        out.append(line)
    return "".join(out)


def _assert_names_supported_path(text: str, doc: str) -> None:
    add_cmd, install_cmd = _install_commands()
    for needle in (add_cmd, install_cmd, MIGRATE_CMD):
        assert needle in text, f"{doc} does not name `{needle}`"
    assert re.search(r"plugin[^.\n]*\bsupported\b|\bsupported\b[^.\n]*plugin", text, re.I), (
        f"{doc} does not call the plugin the supported install"
    )


def _assert_setup_claude_only_deprecated(text: str, doc: str) -> None:
    # No code block runs setup-claude (comment lines are fine).
    for block in re.findall(r"```.*?\n(.*?)```", text, re.DOTALL):
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "setup-claude" not in stripped, (
                f"{doc} has a code block running setup-claude: {stripped!r}"
            )
    # Every prose paragraph mentioning it marks it deprecated or points at the migration.
    for para in re.split(r"\n\s*\n", text):
        if "setup-claude" not in para:
            continue
        assert re.search(r"deprecated", para, re.I) or MIGRATE_CMD in para, (
            f"{doc} mentions setup-claude without marking it deprecated or "
            f"pointing at `{MIGRATE_CMD}`:\n{para}"
        )


def test_readme_names_the_plugin_install_as_supported():
    _assert_names_supported_path(README.read_text(encoding="utf-8"), "README.md")


def test_readme_quick_start_puts_the_plugin_first():
    quick = _section(README.read_text(encoding="utf-8"), "Quick Start")
    add_cmd, install_cmd = _install_commands()
    assert add_cmd in quick and install_cmd in quick, (
        "README's Quick Start does not show the /plugin install commands"
    )
    plugin_at = quick.index(add_cmd)
    for other in ("pipx", "setup-claude"):
        at = quick.find(other)
        if at != -1:
            assert plugin_at < at, (
                f"README's Quick Start mentions `{other}` before the plugin install"
            )


def test_readme_presents_setup_claude_only_as_deprecated():
    _assert_setup_claude_only_deprecated(README.read_text(encoding="utf-8"), "README.md")


def test_infrastructure_names_the_plugin_install_as_supported():
    _assert_names_supported_path(_infrastructure_text(), ".project/INFRASTRUCTURE.md")


def test_infrastructure_presents_setup_claude_only_as_deprecated():
    _assert_setup_claude_only_deprecated(_infrastructure_text(), ".project/INFRASTRUCTURE.md")
