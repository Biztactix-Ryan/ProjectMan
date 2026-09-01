"""US-PM-21 documentation criteria are pinned to the docs that carry them.

- "Docs cover git clean behaviour and the ignored-but-precious nature of
  .project" (US-PM-21-5)
- "Docs describe the private sibling-repo variant for public repos"
  (US-PM-21-6)

The checks are deliberately about substance — the specific flags, commands
and warnings a reader needs — not about prose, so a rewrite that keeps the
facts passes and one that drops them fails.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"
CLI_DOC = DOCS / "reference" / "cli.md"
HUB_DOC = DOCS / "hub-mode" / "git-workflow.md"
TOOLS_DOC = DOCS / "reference" / "mcp-tools.md"
DECISIONS = Path(__file__).resolve().parent.parent / ".project" / "DECISIONS.md"


@pytest.fixture(scope="module")
def section() -> str:
    text = CLI_DOC.read_text()
    start = text.index("## Living with the projectman worktree")
    end = text.index("\n## ", start + 10)
    return text[start:end]


class TestGitCleanAndPrecious:
    def test_the_section_exists_next_to_migrate_and_attach(self):
        text = CLI_DOC.read_text()
        assert text.index("## projectman attach") < text.index(
            "## Living with the projectman worktree"
        )

    def test_git_clean_needs_double_force_to_reach_the_worktree(self, section):
        assert "git clean -fdx" in section
        assert "git clean -ffdx" in section
        assert re.search(r"does \*\*not\*\* descend|does not descend", section)

    def test_the_store_is_called_precious_not_disposable(self, section):
        assert "ignored but precious" in section.lower()
        assert "not disposable" in section

    def test_readers_are_told_how_to_check_before_cleaning(self, section):
        assert "git -C .project status" in section

    def test_fresh_clones_are_pointed_at_attach(self, section):
        assert "projectman attach" in section
        assert "projectman init" in section

    def test_pm_commands_are_documented_as_following_the_store(self, section):
        assert "Branch: projectman" in section
        assert "Pushes **only** `projectman`" in section
        assert "PM store: .project on projectman (worktree)" in section

    def test_the_falsified_hypothesis_is_recorded_not_hidden(self, section):
        assert "zero changes" in section
        assert "false" in section

    def test_adr_001_is_cross_referenced(self, section):
        assert "ADR-001" in section
        assert "DECISIONS.md" in section


class TestPrivateSiblingRepoVariant:
    def test_the_variant_is_named_and_motivated(self, section):
        assert "<repo>-pm" in section
        assert "public" in section.lower()
        assert "private" in section.lower()

    def test_the_commands_are_complete_for_both_ends(self, section):
        assert "git remote add pm" in section
        assert "git push -u pm projectman" in section
        assert "git fetch pm projectman" in section
        assert "git worktree add --track -b projectman .project pm/projectman" in section

    def test_the_trade_offs_are_stated(self, section):
        assert "two repositories" in section
        assert "git push pm projectman" in section
        assert "origin/projectman" in section


class TestOtherDocsAgree:
    def test_hub_workflow_covers_the_store_branch(self):
        text = HUB_DOC.read_text()
        assert "## PM Store on Its Own Branch" in text
        assert "never a gitlink" in text
        assert "living-with-the-projectman-worktree" in text

    def test_mcp_tools_document_the_new_fields(self):
        text = TOOLS_DOC.read_text()
        assert "`pm_store`" in text
        assert "`on_branch`" in text

    def test_adr_001_records_the_verified_outcome(self):
        text = DECISIONS.read_text()
        assert "Verified under US-PM-21" in text
        assert "store_git_state" in text
