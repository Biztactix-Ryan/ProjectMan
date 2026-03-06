"""Tests for cross-repo changesets — grouping related changes across N repos."""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest
import yaml
import frontmatter
from datetime import date
from pathlib import Path

from projectman.models import (
    ChangesetEntry,
    ChangesetFrontmatter,
    ChangesetStatus,
)
from projectman.store import Store


# ─── Model tests ──────────────────────────────────────────────────


class TestChangesetModel:
    def test_changeset_entry(self):
        entry = ChangesetEntry(project="api")
        assert entry.project == "api"
        assert entry.ref == ""
        assert entry.status == "pending"

    def test_changeset_entry_with_ref(self):
        entry = ChangesetEntry(project="frontend", ref="feature/auth", status="merged")
        assert entry.ref == "feature/auth"
        assert entry.status == "merged"

    def test_changeset_frontmatter_defaults(self):
        cs = ChangesetFrontmatter(
            id="CS-PRJ-1",
            title="add-auth",
            created=date.today(),
            updated=date.today(),
        )
        assert cs.status == ChangesetStatus.open
        assert cs.entries == []

    def test_changeset_groups_multiple_projects(self):
        entries = [
            ChangesetEntry(project="api", ref="feature/auth"),
            ChangesetEntry(project="frontend", ref="feature/auth"),
            ChangesetEntry(project="docs", ref="feature/auth"),
        ]
        cs = ChangesetFrontmatter(
            id="CS-PRJ-1",
            title="add-auth",
            entries=entries,
            created=date.today(),
            updated=date.today(),
        )
        assert len(cs.entries) == 3
        assert {e.project for e in cs.entries} == {"api", "frontend", "docs"}

    def test_changeset_id_validation(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChangesetFrontmatter(
                id="123-bad",
                title="test",
                created=date.today(),
                updated=date.today(),
            )


# ─── Store CRUD tests ────────────────────────────────────────────


class TestChangesetStore:
    def test_create_changeset_single_project(self, tmp_project):
        store = Store(tmp_project)
        cs = store.create_changeset("hotfix-db", ["api"])
        assert cs.id == "CS-TST-1"
        assert cs.title == "hotfix-db"
        assert len(cs.entries) == 1
        assert cs.entries[0].project == "api"

    def test_create_changeset_multiple_projects(self, tmp_project):
        store = Store(tmp_project)
        cs = store.create_changeset(
            "add-auth",
            ["api", "frontend", "docs"],
        )
        assert len(cs.entries) == 3
        projects = [e.project for e in cs.entries]
        assert projects == ["api", "frontend", "docs"]

    def test_changeset_persists_to_disk(self, tmp_project):
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "web"])

        # Re-read from disk
        meta, body = store.get_changeset(cs.id)
        assert meta.title == "feature-x"
        assert len(meta.entries) == 2

    def test_list_changesets(self, tmp_project):
        store = Store(tmp_project)
        store.create_changeset("cs-1", ["api"])
        store.create_changeset("cs-2", ["api", "web"])

        all_cs = store.list_changesets()
        assert len(all_cs) == 2

    def test_list_changesets_empty(self, tmp_project):
        store = Store(tmp_project)
        assert store.list_changesets() == []

    def test_add_entry_to_existing_changeset(self, tmp_project):
        store = Store(tmp_project)
        cs = store.create_changeset("feature-y", ["api"])
        assert len(cs.entries) == 1

        updated = store.add_changeset_entry(cs.id, "frontend", ref="feature/y")
        assert len(updated.entries) == 2
        assert updated.entries[1].project == "frontend"
        assert updated.entries[1].ref == "feature/y"

        # Verify persisted
        meta, _ = store.get_changeset(cs.id)
        assert len(meta.entries) == 2

    def test_get_nonexistent_changeset(self, tmp_project):
        store = Store(tmp_project)
        with pytest.raises(FileNotFoundError):
            store.get_changeset("CS-TST-999")

    def test_changeset_groups_n_repos(self, tmp_project):
        """Core acceptance criterion: changesets group related changes across N repos."""
        store = Store(tmp_project)

        # Create a changeset spanning 5 repos
        repos = ["auth-service", "api-gateway", "web-app", "mobile-app", "shared-lib"]
        cs = store.create_changeset("unified-auth-flow", repos)

        assert len(cs.entries) == 5
        assert all(e.status == "pending" for e in cs.entries)

        # Each entry tracks its own project independently
        for i, repo in enumerate(repos):
            assert cs.entries[i].project == repo

        # Round-trip through disk
        meta, _ = store.get_changeset(cs.id)
        assert len(meta.entries) == 5
        assert [e.project for e in meta.entries] == repos

    def test_changeset_increments_id(self, tmp_project):
        store = Store(tmp_project)
        cs1 = store.create_changeset("first", ["a"])
        cs2 = store.create_changeset("second", ["b"])
        assert cs1.id == "CS-TST-1"
        assert cs2.id == "CS-TST-2"

    def test_changeset_with_description(self, tmp_project):
        store = Store(tmp_project)
        cs = store.create_changeset(
            "big-refactor",
            ["api", "web"],
            description="Refactor auth across API and web frontend.",
        )

        meta, body = store.get_changeset(cs.id)
        assert "Refactor auth" in body


# ─── Hub ref update tests ───────────────────────────────────────


def _persist_changeset(store: Store, meta: ChangesetFrontmatter, body: str) -> None:
    """Write updated changeset metadata back to disk."""
    post = frontmatter.Post(content=body, **meta.model_dump(mode="json"))
    store._changeset_path(meta.id).write_text(frontmatter.dumps(post))


def _check_push_readiness(meta: ChangesetFrontmatter) -> tuple[bool, str]:
    """Reproduce the hub-ref-update check from pm_changeset_push.

    Returns (hub_refs_safe, new_status) where hub_refs_safe is True only
    when every entry has status == "merged".
    """
    merged = [e for e in meta.entries if e.status == "merged"]
    pending = [e for e in meta.entries if e.status != "merged"]

    if not pending:
        return True, "merged"
    elif merged:
        return False, "partial"
    else:
        return False, "open"


class TestHubRefsUpdateOnlyWhenAllMerged:
    """Acceptance criterion: Hub refs update only when all changeset PRs merge."""

    def test_all_pending_blocks_hub_update(self, tmp_project):
        """Hub refs must NOT update when no PRs have merged."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        safe, status = _check_push_readiness(cs)
        assert safe is False
        assert status == "open"

    def test_partial_merge_blocks_hub_update(self, tmp_project):
        """Hub refs must NOT update when only some PRs have merged."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        # Simulate: api PR merged, others still pending
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        _persist_changeset(store, meta, body)

        meta, _ = store.get_changeset(cs.id)
        safe, status = _check_push_readiness(meta)
        assert safe is False
        assert status == "partial"

    def test_most_merged_one_pending_blocks_hub_update(self, tmp_project):
        """Hub refs must NOT update even when only 1 of N PRs is still pending."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        meta.entries[1].status = "merged"
        # entries[2] ("worker") stays pending
        _persist_changeset(store, meta, body)

        meta, _ = store.get_changeset(cs.id)
        safe, status = _check_push_readiness(meta)
        assert safe is False
        assert status == "partial"

    def test_all_merged_allows_hub_update(self, tmp_project):
        """Hub refs ARE safe to update when every PR has merged."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.status = "merged"
        _persist_changeset(store, meta, body)

        meta, _ = store.get_changeset(cs.id)
        safe, status = _check_push_readiness(meta)
        assert safe is True
        assert status == "merged"

    def test_push_persists_merged_status(self, tmp_project):
        """When all PRs merge, the changeset status on disk becomes 'merged'."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        # Mark all entries as merged and persist
        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.status = "merged"
        meta.status = ChangesetStatus.merged
        _persist_changeset(store, meta, body)

        # Verify round-trip
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.merged

    def test_push_persists_partial_status(self, tmp_project):
        """When some PRs merge, the changeset status on disk becomes 'partial'."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        meta.status = ChangesetStatus.partial
        _persist_changeset(store, meta, body)

        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.partial

    def test_single_project_changeset_merges_immediately(self, tmp_project):
        """Edge case: a single-project changeset is safe as soon as its one PR merges."""
        store = Store(tmp_project)
        cs = store.create_changeset("hotfix", ["api"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        _persist_changeset(store, meta, body)

        meta, _ = store.get_changeset(cs.id)
        safe, status = _check_push_readiness(meta)
        assert safe is True
        assert status == "merged"


# ─── Status dashboard tests ─────────────────────────────────────


class TestChangesetStatusInDashboard:
    """Acceptance criterion: Changeset status visible in git status dashboard."""

    def test_status_shows_zero_changesets_by_default(self, tmp_project, monkeypatch):
        """pm_status includes changeset count even when none exist."""
        monkeypatch.chdir(tmp_project)
        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())
        assert "changesets" in result
        assert result["changesets"] == 0
        assert result["changesets_by_status"] == {}

    def test_status_shows_open_changesets(self, tmp_project, monkeypatch):
        """Open changesets appear in the status dashboard."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        store.create_changeset("feature-a", ["api", "web"])
        store.create_changeset("feature-b", ["api"])

        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())
        assert result["changesets"] == 2
        assert result["changesets_by_status"]["open"] == 2

    def test_status_shows_mixed_changeset_statuses(self, tmp_project, monkeypatch):
        """Dashboard breaks down changesets by status (open, partial, merged)."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)

        # Create three changesets in different states
        cs_open = store.create_changeset("feature-open", ["api"])

        cs_partial = store.create_changeset("feature-partial", ["api", "web"])
        meta, body = store.get_changeset(cs_partial.id)
        meta.entries[0].status = "merged"
        meta.status = ChangesetStatus.partial
        _persist_changeset(store, meta, body)

        cs_merged = store.create_changeset("feature-merged", ["api", "web"])
        meta, body = store.get_changeset(cs_merged.id)
        for entry in meta.entries:
            entry.status = "merged"
        meta.status = ChangesetStatus.merged
        _persist_changeset(store, meta, body)

        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())
        assert result["changesets"] == 3
        assert result["changesets_by_status"]["open"] == 1
        assert result["changesets_by_status"]["partial"] == 1
        assert result["changesets_by_status"]["merged"] == 1

    def test_status_changeset_count_alongside_stories(self, tmp_project, monkeypatch):
        """Changeset data coexists with story/task counts in the dashboard."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)

        # Create a story and a changeset
        store.create_story("My Story", "Description")
        store.create_changeset("feature-x", ["api"])

        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())
        assert result["stories"] == 1
        assert result["changesets"] == 1
        assert result["changesets_by_status"]["open"] == 1


# ─── changesets.py module tests ─────────────────────────────────


class TestChangesetModule:
    """Tests for the standalone changesets.py convenience functions."""

    def test_create_changeset(self, tmp_project):
        from projectman.changesets import create_changeset

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api", "web"])
        assert cs.id == "CS-TST-1"
        assert len(cs.entries) == 2

    def test_get_changeset(self, tmp_project):
        from projectman.changesets import create_changeset, get_changeset

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api"])
        meta, body = get_changeset(store, cs.id)
        assert meta.title == "feature-z"

    def test_list_changesets(self, tmp_project):
        from projectman.changesets import create_changeset, list_changesets

        store = Store(tmp_project)
        create_changeset(store, "cs-a", ["api"])
        create_changeset(store, "cs-b", ["web"])
        assert len(list_changesets(store)) == 2

    def test_list_changesets_filter_status(self, tmp_project):
        from projectman.changesets import (
            create_changeset,
            list_changesets,
            update_changeset_status,
        )

        store = Store(tmp_project)
        cs = create_changeset(store, "cs-a", ["api"])
        create_changeset(store, "cs-b", ["web"])
        update_changeset_status(store, cs.id, "merged")

        assert len(list_changesets(store, status="merged")) == 1
        assert len(list_changesets(store, status="open")) == 1

    def test_add_project_to_changeset(self, tmp_project):
        from projectman.changesets import (
            add_project_to_changeset,
            create_changeset,
        )

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api"])
        updated = add_project_to_changeset(store, cs.id, "web", ref="feature/z")
        assert len(updated.entries) == 2
        assert updated.entries[1].project == "web"

    def test_update_changeset_status(self, tmp_project):
        from projectman.changesets import (
            create_changeset,
            get_changeset,
            update_changeset_status,
        )

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api", "web"])
        assert cs.status == ChangesetStatus.open

        updated = update_changeset_status(store, cs.id, "partial")
        assert updated.status == ChangesetStatus.partial

        # Verify persisted
        meta, _ = get_changeset(store, cs.id)
        assert meta.status == ChangesetStatus.partial

    def test_update_changeset_status_to_merged(self, tmp_project):
        from projectman.changesets import (
            create_changeset,
            get_changeset,
            update_changeset_status,
        )

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api"])
        update_changeset_status(store, cs.id, "merged")

        meta, _ = get_changeset(store, cs.id)
        assert meta.status == ChangesetStatus.merged

    def test_update_changeset_status_to_closed(self, tmp_project):
        from projectman.changesets import (
            create_changeset,
            get_changeset,
            update_changeset_status,
        )

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api"])
        update_changeset_status(store, cs.id, "closed")

        meta, _ = get_changeset(store, cs.id)
        assert meta.status == ChangesetStatus.closed

    def test_update_changeset_status_invalid(self, tmp_project):
        from projectman.changesets import create_changeset, update_changeset_status

        store = Store(tmp_project)
        cs = create_changeset(store, "feature-z", ["api"])

        with pytest.raises(ValueError):
            update_changeset_status(store, cs.id, "invalid-status")

    def test_update_changeset_status_not_found(self, tmp_project):
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        with pytest.raises(FileNotFoundError):
            update_changeset_status(store, "CS-TST-999", "merged")


# ─── PR cross-reference tests ──────────────────────────────────


class TestPRsCreatedWithCrossReferences:
    """Acceptance criterion: PRs created together with cross-references."""

    def test_pr_commands_generated_for_all_projects(self, tmp_project, monkeypatch):
        """Each project in the changeset gets a PR creation command."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("add-auth", ["api", "frontend", "docs"])

        # Set refs so PRs can be created
        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = f"feature/auth"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        assert len(result["pr_commands"]) == 3
        projects = [cmd["project"] for cmd in result["pr_commands"]]
        assert projects == ["api", "frontend", "docs"]

    def test_pr_body_contains_changeset_title(self, tmp_project, monkeypatch):
        """Each PR body references the changeset title and ID."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("unified-auth", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = "feature/auth"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        for cmd in result["pr_commands"]:
            assert "unified-auth" in cmd["command"]
            assert cs.id in cmd["command"]

    def test_pr_body_contains_cross_references_to_other_projects(
        self, tmp_project, monkeypatch
    ):
        """Each PR body lists all sibling projects as cross-references."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/x"
        meta.entries[1].ref = "feature/x"
        meta.entries[2].ref = "feature/x"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        for cmd in result["pr_commands"]:
            # Each PR command should mention all projects in cross-references
            command_text = cmd["command"]
            assert "api" in command_text
            assert "frontend" in command_text
            assert "worker" in command_text

    def test_pr_title_includes_project_name(self, tmp_project, monkeypatch):
        """PR title includes both the changeset title and the specific project."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("add-auth", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = "feature/auth"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        for cmd in result["pr_commands"]:
            project = cmd["project"]
            assert f"add-auth: {project}" in cmd["command"]

    def test_pr_skips_entries_without_ref(self, tmp_project, monkeypatch):
        """Projects without a branch ref are skipped with a status message."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("feature-y", ["api", "frontend"])

        # Only set ref for api, leave frontend without
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/y"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        commands = result["pr_commands"]
        assert commands[0]["ref"] == "feature/y"
        assert "command" in commands[0]
        assert "skipped" in commands[1]["status"]

    def test_pr_empty_changeset_returns_error(self, tmp_project, monkeypatch):
        """A changeset with no entries returns an error."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("empty-cs", [])

        from projectman.server import pm_changeset_create_prs

        result = pm_changeset_create_prs(cs.id)
        assert "error" in result

    def test_pr_commands_use_correct_branch(self, tmp_project, monkeypatch):
        """Each PR command uses the correct --head branch from the entry ref."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("multi-branch", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].ref = "feature/api-changes"
        meta.entries[1].ref = "feature/frontend-changes"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        assert "--head feature/api-changes" in result["pr_commands"][0]["command"]
        assert "--head feature/frontend-changes" in result["pr_commands"][1]["command"]

    def test_pr_body_includes_description(self, tmp_project, monkeypatch):
        """PR body includes the changeset description when provided."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset(
            "refactor-db",
            ["api", "worker"],
            description="Migrate from MySQL to PostgreSQL across services.",
        )

        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = "feature/pg-migration"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        for cmd in result["pr_commands"]:
            assert "Migrate from MySQL to PostgreSQL" in cmd["command"]

    def test_prs_created_together_same_changeset_id(self, tmp_project, monkeypatch):
        """All PR commands belong to the same changeset, proving they're grouped."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("grouped-feature", ["api", "web", "docs"])

        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = "feature/grouped"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        assert result["changeset"] == cs.id
        assert result["title"] == "grouped-feature"
        # All commands are returned together in one call
        assert len(result["pr_commands"]) == 3


# ─── changeset_check_status tests ──────────────────────────────


def _gh_pr_response(state: str, merged_at=None):
    """Build a mock subprocess result for a gh pr view call."""
    data = {"state": state, "mergedAt": merged_at}
    result = MagicMock()
    result.stdout = json.dumps(data)
    result.returncode = 0
    return result


class TestChangesetCheckStatus:
    """Tests for changeset_check_status() — queries gh pr view per entry."""

    def test_all_merged_sets_status_merged(self, tmp_project):
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        # Add PR numbers to entries
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        meta.entries[1].pr_number = 43
        _persist_changeset(store, meta, body)

        # Create project dirs so cwd is valid
        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "frontend").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")

            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "merged"
        assert result["needs_review"] is False
        assert len(result["entries"]) == 2
        assert all(e["state"] == "MERGED" for e in result["entries"])

        # Verify persisted on disk
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.merged

    def test_partial_merge_sets_status_partial(self, tmp_project):
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        meta.entries[1].pr_number = 43
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "frontend").mkdir(parents=True)

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pr_num = cmd[3]  # gh pr view {number}
            if pr_num == "42":
                return _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")
            return _gh_pr_response("OPEN")

        with patch("projectman.changesets.subprocess.run", side_effect=side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "partial"
        assert result["needs_review"] is False

    def test_closed_pr_flags_for_review(self, tmp_project):
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        meta.entries[1].pr_number = 43
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "frontend").mkdir(parents=True)

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pr_num = cmd[3]
            if pr_num == "42":
                return _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")
            return _gh_pr_response("CLOSED")

        with patch("projectman.changesets.subprocess.run", side_effect=side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "closed"
        assert result["needs_review"] is True

    def test_entries_without_pr_number_skipped(self, tmp_project):
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])
        # No pr_numbers set — entries should be skipped

        result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "open"
        assert all(e["status"] == "no-pr" for e in result["entries"])

    def test_all_open_stays_open(self, tmp_project):
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        meta.entries[1].pr_number = 43
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "frontend").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.return_value = _gh_pr_response("OPEN")
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "open"

    def test_gh_error_recorded(self, tmp_project):
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)

        with patch("projectman.changesets.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh", stderr="not found"
            )
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["entries"][0]["status"] == "error"
        assert "not found" in result["entries"][0]["message"]


# ─── ChangesetEntry pr_number field tests ──────────────────────


class TestChangesetEntryPrNumber:
    def test_pr_number_default_none(self):
        entry = ChangesetEntry(project="api")
        assert entry.pr_number is None

    def test_pr_number_set(self):
        entry = ChangesetEntry(project="api", pr_number=42)
        assert entry.pr_number == 42

    def test_pr_number_roundtrip(self, tmp_project):
        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api"])
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 99
        _persist_changeset(store, meta, body)

        meta2, _ = store.get_changeset(cs.id)
        assert meta2.entries[0].pr_number == 99


# ─── Hub ref gating tests ─────────────────────────────────────


class TestIsProjectBlockedByChangeset:
    """Tests for is_project_blocked_by_changeset()."""

    def test_no_changesets_not_blocked(self, tmp_project):
        from projectman.hub.registry import is_project_blocked_by_changeset

        result = is_project_blocked_by_changeset(tmp_project, "api")
        assert result is None

    def test_open_changeset_blocks_project(self, tmp_project):
        from projectman.hub.registry import is_project_blocked_by_changeset

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        result = is_project_blocked_by_changeset(tmp_project, "api")
        assert result == cs.id

    def test_merged_changeset_does_not_block(self, tmp_project):
        from projectman.hub.registry import is_project_blocked_by_changeset
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api"])
        update_changeset_status(store, cs.id, "merged")

        result = is_project_blocked_by_changeset(tmp_project, "api")
        assert result is None

    def test_partial_changeset_blocks_project(self, tmp_project):
        from projectman.hub.registry import is_project_blocked_by_changeset
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])
        update_changeset_status(store, cs.id, "partial")

        result = is_project_blocked_by_changeset(tmp_project, "api")
        assert result == cs.id

    def test_unrelated_project_not_blocked(self, tmp_project):
        from projectman.hub.registry import is_project_blocked_by_changeset

        store = Store(tmp_project)
        store.create_changeset("feature-x", ["api", "frontend"])

        result = is_project_blocked_by_changeset(tmp_project, "worker")
        assert result is None


class TestUpdateHubRefs:
    """Tests for update_hub_refs() — gated submodule ref updates."""

    def test_rejects_non_merged_changeset(self, tmp_hub):
        from projectman.hub.registry import update_hub_refs

        store = Store(tmp_hub)
        cs = store.create_changeset("feature-x", ["api"])

        result = update_hub_refs(cs.id, root=tmp_hub)
        assert "not merged" in result
        assert "open" in result

    def test_rejects_non_hub_project(self, tmp_project):
        from projectman.hub.registry import update_hub_refs

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api"])
        # Force merged status
        from projectman.changesets import update_changeset_status
        update_changeset_status(store, cs.id, "merged")

        result = update_hub_refs(cs.id, root=tmp_project)
        assert "not a hub project" in result

    def test_updates_refs_on_merged_changeset(self, tmp_hub):
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("feature-x", ["api", "frontend"])
        update_changeset_status(store, cs.id, "merged")

        # Create project directories
        (tmp_hub / "projects" / "api").mkdir(parents=True)
        (tmp_hub / "projects" / "frontend").mkdir(parents=True)

        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = update_hub_refs(cs.id, root=tmp_hub)

        assert "api" in result
        assert "frontend" in result
        # Calls: per project (rev-parse + submodule update + git add + rev-parse) x2
        #        + git commit + rev-parse(hub HEAD) + rev-parse(log) x2 = 10
        git_cmds = [c[0][0][:2] for c in mock_run.call_args_list]
        assert git_cmds.count(["git", "submodule"]) == 2
        assert git_cmds.count(["git", "add"]) == 2
        assert git_cmds.count(["git", "commit"]) == 1

    def test_commit_message_format(self, tmp_hub):
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("unified-auth", ["api", "frontend"])
        update_changeset_status(store, cs.id, "merged")

        (tmp_hub / "projects" / "api").mkdir(parents=True)
        (tmp_hub / "projects" / "frontend").mkdir(parents=True)

        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            update_hub_refs(cs.id, root=tmp_hub)

        # Find the commit call
        commit_call = next(
            c for c in mock_run.call_args_list
            if c[0][0][:2] == ["git", "commit"]
        )
        commit_cmd = commit_call[0][0]
        commit_msg = commit_cmd[3]
        assert "hub: changeset unified-auth merged" in commit_msg
        assert "api" in commit_msg
        assert "frontend" in commit_msg

    def test_no_projects_updated_when_dirs_missing(self, tmp_hub):
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("feature-x", ["nonexistent"])
        update_changeset_status(store, cs.id, "merged")

        result = update_hub_refs(cs.id, root=tmp_hub)
        assert "no projects were updated" in result


# ─── get_changeset_context tests ─────────────────────────────


class TestGetChangesetContext:
    """Tests for get_changeset_context() — changeset info per project for dashboard."""

    def test_no_changesets_returns_empty(self, tmp_project):
        from projectman.hub.registry import get_changeset_context

        result = get_changeset_context(root=tmp_project)
        assert result == {}

    def test_open_changeset_returns_context(self, tmp_project):
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        store.create_changeset("auth-v2", ["api", "web", "worker"])

        result = get_changeset_context(root=tmp_project)
        assert "api" in result
        assert "web" in result
        assert "worker" in result
        assert result["api"]["changeset_name"] == "auth-v2"
        assert result["api"]["changeset_status"] == "open"
        assert result["api"]["total_count"] == 3

    def test_merged_changeset_excluded(self, tmp_project):
        from projectman.hub.registry import get_changeset_context
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs = store.create_changeset("old-feature", ["api"])
        update_changeset_status(store, cs.id, "merged")

        result = get_changeset_context(root=tmp_project)
        assert result == {}

    def test_partial_changeset_included(self, tmp_project):
        from projectman.hub.registry import get_changeset_context
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "web"])
        update_changeset_status(store, cs.id, "partial")

        result = get_changeset_context(root=tmp_project)
        assert "api" in result
        assert result["api"]["changeset_status"] == "partial"

    def test_hub_ref_blocked_flag(self, tmp_project):
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "web", "worker"])

        # Mark api and web as merged, worker still pending
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api
        meta.entries[1].status = "merged"  # web
        meta.entries[2].status = "pending"  # worker
        _persist_changeset(store, meta, body)

        result = get_changeset_context(root=tmp_project)

        # api is merged but worker isn't → hub ref blocked
        assert result["api"]["hub_ref_blocked"] is True
        assert result["api"]["project_pr_status"] == "merged"
        assert "worker" in result["api"]["waiting_on"]

        # worker is not merged → not blocked (nothing to block)
        assert result["worker"]["hub_ref_blocked"] is False
        assert result["worker"]["project_pr_status"] == "pending"

    def test_summary_format(self, tmp_project):
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "web", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api
        meta.entries[1].status = "merged"  # web
        _persist_changeset(store, meta, body)

        result = get_changeset_context(root=tmp_project)
        # worker summary should mention it's waiting on itself (not merged)
        assert "auth-v2" in result["worker"]["summary"]
        assert "2/3 merged" in result["worker"]["summary"]

    def test_waiting_on_list(self, tmp_project):
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "web", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api
        _persist_changeset(store, meta, body)

        result = get_changeset_context(root=tmp_project)
        # api is merged, so it's waiting on web and worker
        assert set(result["api"]["waiting_on"]) == {"web", "worker"}
        # web is not merged, waiting on worker (also not merged)
        assert "worker" in result["web"]["waiting_on"]

    def test_closed_changeset_excluded(self, tmp_project):
        from projectman.hub.registry import get_changeset_context
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs = store.create_changeset("abandoned", ["api"])
        update_changeset_status(store, cs.id, "closed")

        result = get_changeset_context(root=tmp_project)
        assert result == {}


# ─── changeset-status CLI tests ──────────────────────────────


class TestChangesetStatusCLI:
    """Tests for the standalone changeset-status CLI command."""

    def test_no_changesets(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status"])
        assert result.exit_code == 0
        assert "No changesets found" in result.output

    def test_list_all_changesets(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        store.create_changeset("auth-v2", ["api", "web"])
        store.create_changeset("payments", ["api", "worker"])

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status"])
        assert result.exit_code == 0
        assert "auth-v2" in result.output
        assert "payments" in result.output

    def test_filter_by_name(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        store.create_changeset("auth-v2", ["api", "web"])
        store.create_changeset("payments", ["api", "worker"])

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "auth-v2"])
        assert result.exit_code == 0
        assert "auth-v2" in result.output
        assert "payments" not in result.output

    def test_filter_by_id(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "web"])

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", cs.id])
        assert result.exit_code == 0
        assert "auth-v2" in result.output

    def test_no_match(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        store.create_changeset("auth-v2", ["api"])

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "nonexistent"])
        assert result.exit_code == 0
        assert "No changeset found" in result.output

    def test_shows_hub_ref_blocked(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api merged
        meta.entries[1].status = "pending"  # worker pending
        _persist_changeset(store, meta, body)

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "auth-v2"])
        assert result.exit_code == 0
        assert "hub ref blocked" in result.output

    def test_shows_pr_number(self, tmp_project, monkeypatch):
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 42
        _persist_changeset(store, meta, body)

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "auth-v2"])
        assert result.exit_code == 0
        assert "PR #42" in result.output


# ─── Partial merge state reporting tests ────────────────────────


class TestPartialMergeStateClearlyReported:
    """Acceptance criterion: Partial merge state is clearly reported.

    Verifies that when some PRs in a changeset are merged but others are not,
    the partial state is clearly communicated across ALL reporting surfaces:
    changeset_check_status(), pm_changeset_push(), changeset-status CLI,
    pm_status dashboard, and get_changeset_context().
    """

    # --- changeset_check_status() per-entry reporting ---

    def test_check_status_partial_shows_per_entry_breakdown(self, tmp_project):
        """changeset_check_status() entries clearly show which PRs are merged vs open."""
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        meta.entries[1].pr_number = 11
        meta.entries[2].pr_number = 12
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "frontend").mkdir(parents=True)
        (tmp_project / "projects" / "worker").mkdir(parents=True)

        def side_effect(*args, **kwargs):
            pr_num = args[0][3]  # gh pr view {number}
            if pr_num == "10":
                return _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")
            return _gh_pr_response("OPEN")

        with patch("projectman.changesets.subprocess.run", side_effect=side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_project)

        assert result["status"] == "partial"
        # Entry breakdown must identify each project's state
        api_entry = next(e for e in result["entries"] if e["project"] == "api")
        frontend_entry = next(e for e in result["entries"] if e["project"] == "frontend")
        worker_entry = next(e for e in result["entries"] if e["project"] == "worker")

        assert api_entry["state"] == "MERGED"
        assert api_entry["status"] == "merged"
        assert api_entry["merged_at"] is not None

        assert frontend_entry["state"] == "OPEN"
        assert frontend_entry["status"] == "open"

        assert worker_entry["state"] == "OPEN"
        assert worker_entry["status"] == "open"

    def test_check_status_partial_persists_entry_statuses(self, tmp_project):
        """After check_status detects partial, per-entry statuses are persisted to disk."""
        from projectman.changesets import changeset_check_status

        store = Store(tmp_project)
        cs = store.create_changeset("feature-x", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        meta.entries[1].pr_number = 11
        _persist_changeset(store, meta, body)

        (tmp_project / "projects" / "api").mkdir(parents=True)
        (tmp_project / "projects" / "frontend").mkdir(parents=True)

        def side_effect(*args, **kwargs):
            pr_num = args[0][3]
            if pr_num == "10":
                return _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")
            return _gh_pr_response("OPEN")

        with patch("projectman.changesets.subprocess.run", side_effect=side_effect):
            changeset_check_status(store, cs.id, root=tmp_project)

        # Re-read from disk
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.partial
        assert meta.entries[0].status == "merged"
        assert meta.entries[1].status == "open"

    # --- pm_changeset_push() partial reporting ---

    def test_push_partial_lists_merged_and_pending(self, tmp_project, monkeypatch):
        """pm_changeset_push() clearly separates merged and pending projects."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api
        meta.entries[1].status = "pending"  # frontend
        meta.entries[2].status = "pending"  # worker
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_push

        result = yaml.safe_load(pm_changeset_push(cs.id))

        assert result["status"] == "partial"
        assert result["merged"] == ["api"]
        assert len(result["pending"]) == 2
        pending_projects = [p["project"] for p in result["pending"]]
        assert "frontend" in pending_projects
        assert "worker" in pending_projects
        assert "NOT" in result["message"] or "not" in result["message"].lower()

    def test_push_partial_shows_pending_details(self, tmp_project, monkeypatch):
        """pm_changeset_push() pending entries include project name, ref, and status."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        meta.entries[1].ref = "feature/auth"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_push

        result = yaml.safe_load(pm_changeset_push(cs.id))

        assert result["status"] == "partial"
        pending = result["pending"]
        assert len(pending) == 1
        assert pending[0]["project"] == "frontend"
        assert pending[0]["ref"] == "feature/auth"
        assert pending[0]["status"] == "pending"

    # --- changeset-status CLI partial format ---

    def test_cli_shows_merged_count_format(self, tmp_project, monkeypatch):
        """changeset-status shows '(X/Y merged)' count for partial changesets."""
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        _persist_changeset(store, meta, body)

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "auth-v2"])
        assert result.exit_code == 0
        assert "1/3 merged" in result.output

    def test_cli_shows_per_project_status(self, tmp_project, monkeypatch):
        """changeset-status lists each project with its individual status."""
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        meta.entries[1].status = "pending"
        meta.entries[2].status = "pending"
        _persist_changeset(store, meta, body)

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "auth-v2"])
        assert result.exit_code == 0
        # Each project line shows its status
        assert "api: merged" in result.output
        assert "frontend: pending" in result.output
        assert "worker: pending" in result.output

    def test_cli_shows_hub_ref_blocked_only_on_merged_entries(self, tmp_project, monkeypatch):
        """'hub ref blocked' flag appears only for merged entries when others are pending."""
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api
        meta.entries[1].status = "pending"  # frontend
        _persist_changeset(store, meta, body)

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset-status", "auth-v2"])
        assert result.exit_code == 0

        lines = result.output.strip().splitlines()
        api_line = next(l for l in lines if "api:" in l)
        frontend_line = next(l for l in lines if "frontend:" in l)

        assert "hub ref blocked" in api_line
        assert "hub ref blocked" not in frontend_line

    # --- pm_status dashboard partial reporting ---

    def test_dashboard_counts_partial_changesets(self, tmp_project, monkeypatch):
        """pm_status dashboard groups partial changesets separately from open."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)

        # One open, one partial
        store.create_changeset("feature-a", ["api"])

        cs_partial = store.create_changeset("feature-b", ["api", "web"])
        meta, body = store.get_changeset(cs_partial.id)
        meta.entries[0].status = "merged"
        meta.status = ChangesetStatus.partial
        _persist_changeset(store, meta, body)

        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())
        assert result["changesets"] == 2
        assert result["changesets_by_status"]["open"] == 1
        assert result["changesets_by_status"]["partial"] == 1

    # --- get_changeset_context() partial reporting ---

    def test_context_partial_summary_includes_waiting_projects(self, tmp_project):
        """Context summary for partial state names the projects we're waiting on."""
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        meta.entries[1].status = "merged"
        meta.entries[2].status = "pending"
        _persist_changeset(store, meta, body)

        result = get_changeset_context(root=tmp_project)

        # The merged projects should show they're waiting on worker
        assert "worker" in result["api"]["waiting_on"]
        assert "worker" in result["frontend"]["waiting_on"]
        assert result["api"]["hub_ref_blocked"] is True
        assert result["frontend"]["hub_ref_blocked"] is True
        # worker isn't merged so not blocked
        assert result["worker"]["hub_ref_blocked"] is False

    def test_context_partial_merged_count_accurate(self, tmp_project):
        """Context correctly reports merged_count and total_count in partial state."""
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker", "docs"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"  # api
        meta.entries[1].status = "merged"  # frontend
        meta.entries[2].status = "pending"  # worker
        meta.entries[3].status = "pending"  # docs
        _persist_changeset(store, meta, body)

        result = get_changeset_context(root=tmp_project)

        for project in ["api", "frontend", "worker", "docs"]:
            assert result[project]["merged_count"] == 2
            assert result[project]["total_count"] == 4
            assert result[project]["changeset_status"] == "open"  # top-level not updated
            assert "2/4 merged" in result[project]["summary"]

    # --- CLI changeset push partial reporting ---

    def test_cli_push_shows_pending_and_merged_counts(self, tmp_project, monkeypatch):
        """'changeset push' CLI clearly reports pending vs merged breakdown."""
        from click.testing import CliRunner
        from projectman.cli import cli

        monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("auth-v2", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].status = "merged"
        meta.entries[1].status = "pending"
        meta.entries[2].status = "pending"
        _persist_changeset(store, meta, body)

        runner = CliRunner()
        result = runner.invoke(cli, ["changeset", "push", cs.id])
        assert result.exit_code == 0
        assert "NOT ready" in result.output
        assert "2 of 3" in result.output
        assert "api: merged" in result.output
        assert "frontend: pending" in result.output
        assert "worker: pending" in result.output


# ─── Full lifecycle integration test ────────────────────────────


class TestChangesetLifecycle:
    """End-to-end lifecycle: create → PRs → partial merge → all merged → hub ref update."""

    def test_full_lifecycle_create_to_hub_update(self, tmp_hub, monkeypatch):
        """Walk through the complete changeset lifecycle in a single test.

        1. Create changeset with 3 projects → stored in .project/changesets/, status=open
        2. Generate PR commands → 3 PRs with cross-references
        3. Simulate partial merge (2/3) → status=partial, hub refs blocked
        4. Simulate all merged (3/3) → status=merged, hub refs updated
        """
        monkeypatch.chdir(tmp_hub)
        store = Store(tmp_hub)

        # ── Step 1: Create changeset ──
        cs = store.create_changeset("unified-auth", ["api", "frontend", "worker"])
        assert cs.id == "CS-HUB-1"
        assert cs.status == ChangesetStatus.open
        assert len(cs.entries) == 3

        # Verify storage on disk in .project/changesets/
        cs_path = tmp_hub / ".project" / "changesets" / f"{cs.id}.md"
        assert cs_path.exists()

        # ── Step 2: Set refs and generate PR commands ──
        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = "feature/unified-auth"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        pr_result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        assert len(pr_result["pr_commands"]) == 3
        for cmd in pr_result["pr_commands"]:
            assert "unified-auth" in cmd["command"]
            assert cs.id in cmd["command"]

        # Record PR numbers (simulating post-creation)
        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 101
        meta.entries[1].pr_number = 102
        meta.entries[2].pr_number = 103
        _persist_changeset(store, meta, body)

        # ── Step 3: Partial merge (2/3) ──
        (tmp_hub / "projects" / "api").mkdir(parents=True)
        (tmp_hub / "projects" / "frontend").mkdir(parents=True)
        (tmp_hub / "projects" / "worker").mkdir(parents=True)

        from projectman.changesets import changeset_check_status

        def partial_side_effect(*args, **kwargs):
            pr_num = args[0][3]
            if pr_num in ("101", "102"):
                return _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")
            return _gh_pr_response("OPEN")

        with patch("projectman.changesets.subprocess.run", side_effect=partial_side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_hub)

        assert result["status"] == "partial"

        # Hub refs must NOT be updated in partial state
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.partial

        from projectman.hub.registry import update_hub_refs

        hub_result = update_hub_refs(cs.id, root=tmp_hub)
        assert "not merged" in hub_result

        # ── Step 4: All merged (3/3) ──
        def all_merged_side_effect(*args, **kwargs):
            return _gh_pr_response("MERGED", "2026-02-19T14:00:00Z")

        with patch("projectman.changesets.subprocess.run", side_effect=all_merged_side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_hub)

        assert result["status"] == "merged"

        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.merged
        assert all(e.status == "merged" for e in meta.entries)

        # Hub refs now safe to update
        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            hub_result = update_hub_refs(cs.id, root=tmp_hub)

        assert "api" in hub_result
        assert "frontend" in hub_result
        assert "worker" in hub_result
        # Verify core git operations happened
        git_cmds = [c[0][0][:2] for c in mock_run.call_args_list]
        assert git_cmds.count(["git", "submodule"]) == 3
        assert git_cmds.count(["git", "add"]) == 3
        assert git_cmds.count(["git", "commit"]) == 1

    def test_lifecycle_pr_rejected_flags_changeset(self, tmp_hub):
        """When one PR is closed without merge, the changeset is flagged for review."""
        store = Store(tmp_hub)
        cs = store.create_changeset("feature-x", ["api", "frontend", "worker"])

        meta, body = store.get_changeset(cs.id)
        meta.entries[0].pr_number = 10
        meta.entries[1].pr_number = 11
        meta.entries[2].pr_number = 12
        _persist_changeset(store, meta, body)

        (tmp_hub / "projects" / "api").mkdir(parents=True)
        (tmp_hub / "projects" / "frontend").mkdir(parents=True)
        (tmp_hub / "projects" / "worker").mkdir(parents=True)

        from projectman.changesets import changeset_check_status

        def side_effect(*args, **kwargs):
            pr_num = args[0][3]
            if pr_num == "10":
                return _gh_pr_response("MERGED", "2026-02-19T12:00:00Z")
            if pr_num == "11":
                return _gh_pr_response("CLOSED")  # Rejected
            return _gh_pr_response("OPEN")

        with patch("projectman.changesets.subprocess.run", side_effect=side_effect):
            result = changeset_check_status(store, cs.id, root=tmp_hub)

        assert result["status"] == "closed"
        assert result["needs_review"] is True

        # Verify per-entry status breakdown
        api = next(e for e in result["entries"] if e["project"] == "api")
        frontend = next(e for e in result["entries"] if e["project"] == "frontend")
        worker = next(e for e in result["entries"] if e["project"] == "worker")
        assert api["status"] == "merged"
        assert frontend["status"] == "closed"
        assert worker["status"] == "open"

        # Changeset on disk reflects closed status
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.closed


# ─── Multiple active changesets tests ───────────────────────────


class TestMultipleActiveChangesets:
    """DoD scenario 8: 2 changesets with overlapping projects tracked independently."""

    def test_overlapping_projects_tracked_independently(self, tmp_project):
        """Two changesets sharing 'api' are stored and listed independently."""
        store = Store(tmp_project)

        cs1 = store.create_changeset("auth-feature", ["api", "frontend"])
        cs2 = store.create_changeset("payment-feature", ["api", "worker"])

        assert cs1.id != cs2.id
        assert cs1.id == "CS-TST-1"
        assert cs2.id == "CS-TST-2"

        all_cs = store.list_changesets()
        assert len(all_cs) == 2

        # Both mention "api" but are distinct objects
        cs1_projects = {e.project for e in cs1.entries}
        cs2_projects = {e.project for e in cs2.entries}
        assert cs1_projects == {"api", "frontend"}
        assert cs2_projects == {"api", "worker"}

    def test_independent_status_progression(self, tmp_project):
        """Merging one changeset doesn't affect the other."""
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs1 = store.create_changeset("auth-feature", ["api", "frontend"])
        cs2 = store.create_changeset("payment-feature", ["api", "worker"])

        # Merge cs1 only
        update_changeset_status(store, cs1.id, "merged")

        meta1, _ = store.get_changeset(cs1.id)
        meta2, _ = store.get_changeset(cs2.id)
        assert meta1.status == ChangesetStatus.merged
        assert meta2.status == ChangesetStatus.open  # Unchanged

    def test_overlapping_project_blocked_by_either_changeset(self, tmp_project):
        """'api' is blocked if ANY open changeset includes it."""
        from projectman.hub.registry import is_project_blocked_by_changeset
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs1 = store.create_changeset("auth-feature", ["api", "frontend"])
        cs2 = store.create_changeset("payment-feature", ["api", "worker"])

        # api is blocked by cs1 (first open changeset found)
        blocker = is_project_blocked_by_changeset(tmp_project, "api")
        assert blocker is not None

        # Merge cs1 — api still blocked by cs2
        update_changeset_status(store, cs1.id, "merged")
        blocker = is_project_blocked_by_changeset(tmp_project, "api")
        assert blocker == cs2.id

        # Merge cs2 — api is now free
        update_changeset_status(store, cs2.id, "merged")
        blocker = is_project_blocked_by_changeset(tmp_project, "api")
        assert blocker is None

    def test_context_reports_multiple_changesets_per_project(self, tmp_project):
        """get_changeset_context returns the latest open changeset context per project."""
        from projectman.hub.registry import get_changeset_context

        store = Store(tmp_project)
        store.create_changeset("auth-feature", ["api", "frontend"])
        store.create_changeset("payment-feature", ["api", "worker"])

        context = get_changeset_context(root=tmp_project)

        # api appears in context (from whichever changeset is last in list)
        assert "api" in context
        assert "frontend" in context
        assert "worker" in context

    def test_dashboard_counts_both_changesets(self, tmp_project, monkeypatch):
        """pm_status counts both changesets independently."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        store.create_changeset("auth-feature", ["api", "frontend"])
        store.create_changeset("payment-feature", ["api", "worker"])

        from projectman.server import pm_status

        result = yaml.safe_load(pm_status())
        assert result["changesets"] == 2
        assert result["changesets_by_status"]["open"] == 2

    def test_list_filter_works_with_multiple_changesets(self, tmp_project):
        """Filtering by status correctly selects from multiple changesets."""
        from projectman.changesets import update_changeset_status

        store = Store(tmp_project)
        cs1 = store.create_changeset("auth-feature", ["api", "frontend"])
        cs2 = store.create_changeset("payment-feature", ["api", "worker"])

        update_changeset_status(store, cs1.id, "merged")

        open_cs = store.list_changesets(status="open")
        merged_cs = store.list_changesets(status="merged")
        assert len(open_cs) == 1
        assert open_cs[0].id == cs2.id
        assert len(merged_cs) == 1
        assert merged_cs[0].id == cs1.id


# ─── Add project mid-flight tests ──────────────────────────────


class TestAddProjectMidFlight:
    """DoD scenario 7: add a 4th project to an existing 3-project changeset."""

    def test_add_fourth_project_mid_flight(self, tmp_project):
        """Adding a 4th project to a 3-project changeset works correctly."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-z", ["api", "frontend", "worker"])
        assert len(cs.entries) == 3

        updated = store.add_changeset_entry(cs.id, "mobile", ref="feature/z")
        assert len(updated.entries) == 4
        assert updated.entries[3].project == "mobile"
        assert updated.entries[3].ref == "feature/z"
        assert updated.entries[3].status == "pending"

        # Original entries untouched
        assert updated.entries[0].project == "api"
        assert updated.entries[1].project == "frontend"
        assert updated.entries[2].project == "worker"

        # Persisted to disk
        meta, _ = store.get_changeset(cs.id)
        assert len(meta.entries) == 4

    def test_added_project_included_in_pr_generation(self, tmp_project, monkeypatch):
        """PRs generated after adding a project include the new project."""
        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs = store.create_changeset("feature-z", ["api", "frontend", "worker"])

        # Add 4th project
        store.add_changeset_entry(cs.id, "mobile", ref="feature/z")

        # Set refs for all
        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.ref = "feature/z"
        _persist_changeset(store, meta, body)

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs.id))
        assert len(result["pr_commands"]) == 4
        projects = [cmd["project"] for cmd in result["pr_commands"]]
        assert "mobile" in projects

    def test_added_project_blocks_hub_ref_update(self, tmp_project):
        """The newly added project must also be merged before hub refs update."""
        store = Store(tmp_project)
        cs = store.create_changeset("feature-z", ["api", "frontend"])

        # Mark originals as merged
        meta, body = store.get_changeset(cs.id)
        for entry in meta.entries:
            entry.status = "merged"
        _persist_changeset(store, meta, body)

        # Add a new project (still pending)
        store.add_changeset_entry(cs.id, "worker")

        meta, _ = store.get_changeset(cs.id)
        safe, status = _check_push_readiness(meta)
        assert safe is False
        assert status == "partial"


# ─── Storage path verification tests ───────────────────────────


class TestChangesetStoragePath:
    """DoD scenario 1: changesets stored in .project/changesets/."""

    def test_changeset_stored_in_changesets_dir(self, tmp_project):
        """Changeset files are stored under .project/changesets/."""
        store = Store(tmp_project)
        cs = store.create_changeset("test-cs", ["api", "web", "worker"])

        expected_dir = tmp_project / ".project" / "changesets"
        expected_file = expected_dir / f"{cs.id}.md"
        assert expected_dir.exists()
        assert expected_file.exists()

# ─── Hub auto-rebase on push conflict tests ────────────────────


class TestHubAutoRebasesOnPushConflict:
    """Acceptance criterion: Hub auto-rebases submodule ref updates on push conflict.

    push_hub() delegates to hub_push_with_rebase() which uses
    git fetch + git rebase origin/main (not git pull --rebase).
    """

    def test_push_succeeds_first_try_no_rebase(self, tmp_hub):
        """When push succeeds on first attempt, no rebase is needed."""
        from projectman.hub.registry import push_hub

        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = push_hub(root=tmp_hub)

        assert result["status"] == "pushed"
        assert result["attempts"] == 1

    def test_push_conflict_triggers_rebase_and_retry(self, tmp_hub):
        """When push fails with conflict, hub auto-rebases and retries push."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 2

    def test_rebase_failure_flags_manual_resolution(self, tmp_hub):
        """When rebase fails, the conflict is flagged clearly."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            # diff for classify returns unknown (no projects/ or .project/)
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert "manual resolution" in result["error"]

    def test_push_retries_up_to_max_limit(self, tmp_hub):
        """Push is retried up to max_retries times before giving up."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=3)

        assert result["status"] == "failed"
        assert result["attempts"] == 3
        assert "max retries" in result["error"]

    def test_push_succeeds_after_multiple_rebases(self, tmp_hub):
        """Push can succeed after multiple rebase attempts within the retry limit."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] < 3:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=5)

        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 3

    def test_non_hub_project_returns_error(self, tmp_project):
        """push_hub rejects non-hub projects."""
        from projectman.hub.registry import push_hub

        result = push_hub(root=tmp_project)
        assert result["status"] == "failed"
        assert "not a hub project" in result["error"]

    def test_rebase_abort_called_on_rebase_failure(self, tmp_hub):
        """When rebase fails, git rebase --abort is called to clean up."""
        from projectman.hub.registry import push_hub

        calls = []

        def side_effect(cmd, **kwargs):
            calls.append(list(cmd[:3]))
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            push_hub(root=tmp_hub)

        assert ["git", "rebase", "--abort"] in calls

    def test_non_conflict_push_error_not_retried(self, tmp_hub):
        """Push errors unrelated to conflicts (e.g. auth failure) are not retried."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="fatal: Authentication failed")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert result["attempts"] == 1
        assert "Authentication failed" in result["error"]


# ─── Storage path verification tests ───────────────────────────


class TestChangesetStoragePath:
    """DoD scenario 1: changesets stored in .project/changesets/."""

    def test_changeset_file_is_valid_frontmatter(self, tmp_project):
        """Changeset files on disk have valid YAML frontmatter."""
        store = Store(tmp_project)
        cs = store.create_changeset("test-cs", ["api", "web", "worker"])

        path = tmp_project / ".project" / "changesets" / f"{cs.id}.md"
        post = frontmatter.load(str(path))
        assert post.metadata["id"] == cs.id
        assert post.metadata["title"] == "test-cs"
        assert post.metadata["status"] == "open"
        assert len(post.metadata["entries"]) == 3


# ─── Fast-forwardable ref conflict resolution tests ─────────────


class TestFastForwardableRefConflictsResolved:
    """Acceptance criterion: Fast-forwardable ref conflicts resolved automatically.

    push_hub() delegates to hub_push_with_rebase() which uses
    git fetch + git rebase origin/main for conflict resolution.
    """

    def test_disjoint_submodule_updates_resolved_by_rebase(self, tmp_hub):
        """Two developers updating different submodule refs → rebase resolves it."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 2
        assert "error" not in result

    def test_same_submodule_fast_forward_resolved_by_rebase(self, tmp_hub):
        """Same submodule ref updated to a descendant commit → rebase resolves it."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="failed to push some refs")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 2

    def test_diverged_refs_not_fast_forwardable(self, tmp_hub):
        """Same submodule ref diverged → flagged for manual resolution."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            # _classify_rebase_conflict → "unknown" triggers generic message
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert "manual resolution" in result["error"]

    def test_mixed_fast_forward_and_disjoint_resolves(self, tmp_hub):
        """Mix of disjoint and fast-forwardable changes → all resolve."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 2

    def test_fast_forward_resolution_preserves_both_ref_updates(self, tmp_hub):
        """After rebase, the push sequence includes fetch + rebase + push."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}
        operations = []

        def side_effect(cmd, **kwargs):
            operations.append(list(cmd[:3]))
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "rebased_and_pushed"
        # Verify push → fetch → ... → rebase → push sequence
        push_indices = [i for i, op in enumerate(operations) if op[:2] == ["git", "push"]]
        assert len(push_indices) == 2
        fetch_indices = [i for i, op in enumerate(operations) if op[:2] == ["git", "fetch"]]
        assert len(fetch_indices) >= 1
        rebase_indices = [i for i, op in enumerate(operations) if op[:2] == ["git", "rebase"] and "--abort" not in op]
        assert len(rebase_indices) >= 1

    def test_concurrent_race_resolved_after_two_rebases(self, tmp_hub):
        """Push keeps failing with conflict → resolved after two rebases."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] <= 2:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=5)

        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 3

    def test_update_hub_refs_then_push_fast_forward_lifecycle(self, tmp_hub):
        """End-to-end: update_hub_refs commits ref changes, push_hub resolves
        a fast-forwardable conflict, and the commit lands successfully.
        """
        from projectman.hub.registry import update_hub_refs, push_hub
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("feature-y", ["api", "frontend"])
        update_changeset_status(store, cs.id, "merged")

        (tmp_hub / "projects" / "api").mkdir(parents=True)
        (tmp_hub / "projects" / "frontend").mkdir(parents=True)

        # Step 1: update_hub_refs creates the commit
        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ref_result = update_hub_refs(cs.id, root=tmp_hub)

        assert "api" in ref_result
        assert "frontend" in ref_result

        # Step 2: push_hub encounters a conflict and resolves via rebase
        push_count = {"n": 0}

        def push_side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=push_side_effect):
            push_result = push_hub(root=tmp_hub)

        assert push_result["status"] == "rebased_and_pushed"
        assert push_result["attempts"] == 2


# ─── Non-fast-forward conflict flagging tests ─────────────────


class TestNonFastForwardConflictsFlagged:
    """Acceptance criterion: Non-fast-forward conflicts flagged clearly for manual resolution.

    push_hub() delegates to hub_push_with_rebase() which classifies
    conflicts and reports clear error messages for manual resolution.
    """

    def test_diverged_refs_error_contains_resolution_hint(self, tmp_hub):
        """Error message indicates manual resolution is required."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert "manual resolution" in result["error"]

    def test_error_includes_submodule_ref_conflict_type(self, tmp_hub):
        """Error distinguishes submodule ref conflicts from .project/ conflicts."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            # _classify → submodule_ref
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="projects/billing\n")
            # _get_conflicting_submodule_refs → no conflicts parsed
            if cmd[:2] == ["git", "ls-files"]:
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert "submodule ref conflict" in result["error"]

    def test_rebase_abort_cleans_up_on_non_fast_forward(self, tmp_hub):
        """When conflict is detected, rebase is aborted to leave repo clean."""
        from projectman.hub.registry import push_hub

        calls = []

        def side_effect(cmd, **kwargs):
            calls.append(list(cmd[:3]))
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            push_hub(root=tmp_hub)

        assert ["git", "rebase", "--abort"] in calls

    def test_non_fast_forward_does_not_retry_after_rebase_failure(self, tmp_hub):
        """Once a conflict is detected, no further push retries occur."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=5)

        # Only one push call — rebase failure stops the retry loop
        assert push_count["n"] == 1
        assert result["status"] == "failed"

    def test_project_file_conflict_reported_separately(self, tmp_hub):
        """When .project/ files conflict, the error mentions .project/."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout=".project/index.yaml\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert ".project/" in result["error"]
        assert "manual resolution" in result["error"]

    def test_non_fast_forward_status_is_failed_not_pushed(self, tmp_hub):
        """Conflicts return status 'failed', never 'pushed' or 'rebased_and_pushed'."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="failed to push some refs")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "failed"
        assert result["status"] not in ("pushed", "rebased_and_pushed")
        assert "error" in result
        assert result["error"]  # non-empty


# ─── Push retried after successful rebase tests ───────────────


class TestPushRetriedAfterSuccessfulRebase:
    """Acceptance criterion: Push retried after successful rebase.

    push_hub() delegates to hub_push_with_rebase() which uses
    git fetch + git rebase origin/main, then retries the push.
    """

    def test_push_is_retried_after_successful_rebase(self, tmp_hub):
        """After a successful rebase, git push is called again."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}
        commands = []

        def side_effect(cmd, **kwargs):
            commands.append(list(cmd[:3]))
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        # Verify: push (fail) → fetch → ... → rebase → push (succeed)
        push_indices = [i for i, c in enumerate(commands) if c[:2] == ["git", "push"]]
        assert len(push_indices) == 2
        assert push_count["n"] == 2
        assert result["status"] == "rebased_and_pushed"

    def test_retry_push_runs_in_same_working_directory(self, tmp_hub):
        """Both the original and retried push use the hub root as cwd."""
        from projectman.hub.registry import push_hub

        push_cwds = []
        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_cwds.append(kwargs.get("cwd"))
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            push_hub(root=tmp_hub)

        assert len(push_cwds) == 2
        assert push_cwds[0] == push_cwds[1] == str(tmp_hub)

    def test_successful_retry_reports_rebased_and_pushed(self, tmp_hub):
        """When the retried push succeeds, status is 'rebased_and_pushed'."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert result["status"] == "rebased_and_pushed"
        assert result["status"] != "pushed"
        assert result["attempts"] == 2
        assert "error" not in result

    def test_retry_push_failure_triggers_another_rebase_cycle(self, tmp_hub):
        """If the retried push also fails with a conflict, another rebase+push cycle runs."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}
        commands = []

        def side_effect(cmd, **kwargs):
            commands.append(list(cmd[:3]))
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] <= 2:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=5)

        # Three pushes: fail, fail, succeed
        push_indices = [i for i, c in enumerate(commands) if c[:2] == ["git", "push"]]
        assert len(push_indices) == 3
        assert push_count["n"] == 3
        assert result["status"] == "rebased_and_pushed"
        assert result["attempts"] == 3

    def test_no_retry_when_rebase_fails(self, tmp_hub):
        """If rebase fails, push is NOT retried."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                return MagicMock(returncode=1, stderr="rejected non-fast-forward")
            if cmd[:2] == ["git", "rebase"] and "--abort" not in cmd:
                return MagicMock(returncode=1, stderr="CONFLICT")
            if cmd[:2] == ["git", "diff"] and "--diff-filter=U" in cmd:
                return MagicMock(returncode=0, stdout="README.md\n")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=5)

        # Only one push attempt — failed rebase stops the loop
        assert push_count["n"] == 1
        assert result["status"] == "failed"

    def test_attempt_count_reflects_actual_push_calls(self, tmp_hub):
        """The 'attempts' field matches the number of actual git push calls."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] < 4:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub, max_retries=5)

        assert result["attempts"] == 4
        assert push_count["n"] == 4
        assert result["status"] == "rebased_and_pushed"


# ─── Ref update history logged for audit tests ────────────────


class TestRefUpdateHistoryLoggedForAudit:
    """Acceptance criterion: Ref update history logged for audit.

    Every ref update must leave an auditable trail — structured commit messages
    from update_hub_refs(), status/attempt metadata from push_hub(), and
    changeset status transitions that together form a complete audit log.
    """

    def test_commit_message_contains_changeset_name(self, tmp_hub):
        """The commit created by update_hub_refs includes the changeset title for traceability."""
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("auth-rollout", ["api", "frontend"])
        update_changeset_status(store, cs.id, "merged")

        (tmp_hub / "projects" / "api").mkdir(parents=True)
        (tmp_hub / "projects" / "frontend").mkdir(parents=True)

        commit_messages = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[:2] == ["git", "commit"]:
                commit_messages.append(cmd[3])  # cmd is [git, commit, -m, msg]
            return MagicMock(returncode=0)

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            update_hub_refs(cs.id, root=tmp_hub)

        assert len(commit_messages) == 1
        assert "auth-rollout" in commit_messages[0]

    def test_commit_message_lists_all_updated_projects(self, tmp_hub):
        """The commit message enumerates every project whose ref was updated."""
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("multi-deploy", ["api", "frontend", "worker"])
        update_changeset_status(store, cs.id, "merged")

        for name in ("api", "frontend", "worker"):
            (tmp_hub / "projects" / name).mkdir(parents=True)

        commit_messages = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[:2] == ["git", "commit"]:
                commit_messages.append(cmd[3])
            return MagicMock(returncode=0)

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            update_hub_refs(cs.id, root=tmp_hub)

        msg = commit_messages[0]
        assert "api" in msg
        assert "frontend" in msg
        assert "worker" in msg

    def test_commit_message_has_hub_prefix(self, tmp_hub):
        """Commit messages start with 'hub:' prefix so they can be filtered in git log."""
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("db-migration", ["api"])
        update_changeset_status(store, cs.id, "merged")

        (tmp_hub / "projects" / "api").mkdir(parents=True)

        commit_messages = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[:2] == ["git", "commit"]:
                commit_messages.append(cmd[3])
            return MagicMock(returncode=0)

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            update_hub_refs(cs.id, root=tmp_hub)

        assert commit_messages[0].startswith("hub:")

    def test_push_result_includes_attempt_count_for_audit(self, tmp_hub):
        """push_hub result always includes 'attempts' so audit can track retry history."""
        from projectman.hub.registry import push_hub

        # Successful first try
        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = push_hub(root=tmp_hub)

        assert "attempts" in result
        assert result["attempts"] == 1

    def test_push_result_includes_status_for_audit(self, tmp_hub):
        """push_hub result always includes 'status' reflecting whether rebase was needed."""
        from projectman.hub.registry import push_hub

        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert "status" in result
        assert result["status"] == "rebased_and_pushed"

    def test_failed_push_includes_error_for_audit(self, tmp_hub):
        """Failed pushes include an 'error' field with the failure reason."""
        from projectman.hub.registry import push_hub

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                return MagicMock(returncode=1, stderr="fatal: remote hung up unexpectedly")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            result = push_hub(root=tmp_hub)

        assert "error" in result
        assert result["error"]  # non-empty
        assert "remote hung up" in result["error"]

    def test_changeset_status_transitions_are_persisted(self, tmp_hub):
        """Changeset status changes are written to disk so they survive restarts."""
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("track-me", ["api"])

        # Transition through statuses
        update_changeset_status(store, cs.id, "partial")
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.partial

        update_changeset_status(store, cs.id, "merged")
        meta, _ = store.get_changeset(cs.id)
        assert meta.status == ChangesetStatus.merged

    def test_changeset_updated_date_tracks_last_modification(self, tmp_hub):
        """Each changeset status update refreshes the 'updated' timestamp."""
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("dated-cs", ["api"])

        update_changeset_status(store, cs.id, "merged")
        meta, _ = store.get_changeset(cs.id)
        assert meta.updated == date.today()

    def test_update_hub_refs_return_value_identifies_projects(self, tmp_hub):
        """update_hub_refs returns a string listing the projects that were updated."""
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("audit-test", ["billing", "notifications"])
        update_changeset_status(store, cs.id, "merged")

        (tmp_hub / "projects" / "billing").mkdir(parents=True)
        (tmp_hub / "projects" / "notifications").mkdir(parents=True)

        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = update_hub_refs(cs.id, root=tmp_hub)

        assert "billing" in result
        assert "notifications" in result

    def test_push_result_distinguishes_clean_push_from_rebased(self, tmp_hub):
        """Audit can distinguish a clean push ('pushed') from one that needed rebase ('rebased_and_pushed')."""
        from projectman.hub.registry import push_hub

        # Clean push
        with patch("projectman.hub.registry.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            clean = push_hub(root=tmp_hub)

        assert clean["status"] == "pushed"

        # Rebased push
        push_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                push_count["n"] += 1
                if push_count["n"] == 1:
                    return MagicMock(returncode=1, stderr="rejected non-fast-forward")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            rebased = push_hub(root=tmp_hub)

        assert rebased["status"] == "rebased_and_pushed"
        assert clean["status"] != rebased["status"]

    def test_per_entry_status_tracked_in_changeset(self, tmp_hub):
        """Individual project entries within a changeset track their own status."""
        store = Store(tmp_hub)
        cs = store.create_changeset("entry-audit", ["api", "frontend"])

        # Each entry starts with a status
        for entry in cs.entries:
            assert entry.status == "pending"

    def test_commit_message_format_is_grep_friendly(self, tmp_hub):
        """Commit messages follow a consistent format searchable via git log --grep."""
        from projectman.hub.registry import update_hub_refs
        from projectman.changesets import update_changeset_status

        store = Store(tmp_hub)
        cs = store.create_changeset("search-me", ["api"])
        update_changeset_status(store, cs.id, "merged")

        (tmp_hub / "projects" / "api").mkdir(parents=True)

        commit_messages = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[:2] == ["git", "commit"]:
                commit_messages.append(cmd[3])
            return MagicMock(returncode=0)

        with patch("projectman.hub.registry.subprocess.run", side_effect=side_effect):
            update_hub_refs(cs.id, root=tmp_hub)

        msg = commit_messages[0]
        # Format: "hub: changeset {title} merged — update {projects}"
        assert msg.startswith("hub: changeset ")
        assert "merged" in msg
        assert "update" in msg
