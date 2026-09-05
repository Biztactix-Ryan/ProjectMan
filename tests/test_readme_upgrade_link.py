"""US-PM-23-3 — README points at the Upgrading section from its install steps.

US-PM-23's acceptance criterion: "README links to the Upgrading section from
its install instructions". The link is the only thing carrying a reader from
"I installed it" to "…and here is how to refresh it from my checkout", so it
is pinned from both ends: the README must carry the link, and
``docs/installation.md`` must still have the heading the link's ``#upgrading``
fragment resolves against. Either half moving alone leaves a dead anchor that
renders fine on GitHub and goes nowhere.

The commands themselves are deliberately *not* asserted here — they live in
``docs/installation.md`` and duplicating them in the README is what this task
avoids.

This module only reads the repository.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
INSTALL_DOC = REPO_ROOT / "docs" / "installation.md"

#: ``[Upgrading](docs/installation.md#upgrading)`` — any link text, that target.
UPGRADE_LINK_RE = re.compile(r"\[[^\]]+\]\(docs/installation\.md#upgrading\)")

#: The heading GitHub turns into the ``#upgrading`` anchor.
UPGRADING_HEADING_RE = re.compile(r"^##\s+Upgrading\s*$", re.MULTILINE)


def test_readme_links_to_the_upgrading_section():
    """The README carries a link whose target is ``docs/installation.md#upgrading``."""
    text = README.read_text(encoding="utf-8")
    assert UPGRADE_LINK_RE.search(text), (
        "README.md has no link targeting `docs/installation.md#upgrading`; a "
        "developer finishing the install steps has nothing telling them how to "
        "refresh a pipx install from their working tree."
    )


def test_installation_doc_has_the_upgrading_heading():
    """``docs/installation.md`` still has the ``## Upgrading`` heading the link needs."""
    text = INSTALL_DOC.read_text(encoding="utf-8")
    assert UPGRADING_HEADING_RE.search(text), (
        f"{INSTALL_DOC.relative_to(REPO_ROOT)} has no `## Upgrading` heading, so "
        "the README's `#upgrading` anchor resolves to nothing on GitHub."
    )
