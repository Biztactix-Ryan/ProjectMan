"""Tests for actor field population in activity log entries (US-PRJ-18-5).

Verifies that the actor field is populated from:
1. PROJECTMAN_ACTOR env var (highest priority)
2. git config user.name (fallback)
3. "unknown" (final fallback)
"""

import json

import pytest

from projectman.store import Store


def _read_log(store: Store) -> list[dict]:
    """Read all log entries from the store's activity log."""
    log_path = store.project_dir / "activity.jsonl"
    if not log_path.exists():
        return []
    lines = log_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class TestActorFromEnvVar:
    """PROJECTMAN_ACTOR env var takes highest priority."""

    def test_actor_from_env_var(self, store, monkeypatch):
        monkeypatch.setenv("PROJECTMAN_ACTOR", "alice")
        store.create_story("Story", "Desc")
        entries = _read_log(store)
        assert len(entries) >= 1
        assert entries[0]["actor"] == "alice"

    def test_env_var_overrides_git_config(self, tmp_git_project, monkeypatch):
        """Env var wins even when git config user.name is set."""
        monkeypatch.setenv("PROJECTMAN_ACTOR", "env-user")
        git_store = Store(tmp_git_project)
        git_store.create_story("Story", "Desc")
        entries = _read_log(git_store)
        assert entries[0]["actor"] == "env-user"


class TestActorFromGitConfig:
    """git config user.name is used when no env var is set."""

    def test_actor_from_git_config(self, tmp_git_project, monkeypatch):
        monkeypatch.delenv("PROJECTMAN_ACTOR", raising=False)
        git_store = Store(tmp_git_project)
        git_store.create_story("Story", "Desc")
        entries = _read_log(git_store)
        assert entries[0]["actor"] == "Test"  # set in conftest tmp_git_project

    def test_actor_from_git_config_on_update(self, tmp_git_project, monkeypatch):
        monkeypatch.delenv("PROJECTMAN_ACTOR", raising=False)
        git_store = Store(tmp_git_project)
        git_store.create_story("Story", "Desc")
        git_store.update("US-TST-1", status="active")
        entries = _read_log(git_store)
        update_entries = [e for e in entries if e["event_type"] == "update"]
        assert len(update_entries) == 1
        assert update_entries[0]["actor"] == "Test"


class TestActorFallback:
    """Falls back to 'unknown' when no env var or git config is available."""

    def test_actor_falls_back_to_unknown(self, store, monkeypatch):
        monkeypatch.delenv("PROJECTMAN_ACTOR", raising=False)
        # Isolate from global/system git config so user.name is unset
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
        store.create_story("Story", "Desc")
        entries = _read_log(store)
        assert entries[0]["actor"] == "unknown"


class TestActorConsistency:
    """Actor field is populated consistently across all mutation types."""

    def test_actor_on_create_story(self, store, monkeypatch):
        monkeypatch.setenv("PROJECTMAN_ACTOR", "bot")
        store.create_story("Story", "Desc")
        entries = _read_log(store)
        story_entries = [e for e in entries if e["item_type"] == "story"]
        assert all(e["actor"] == "bot" for e in story_entries)

    def test_actor_on_create_task(self, store, monkeypatch):
        monkeypatch.setenv("PROJECTMAN_ACTOR", "bot")
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Desc")
        entries = _read_log(store)
        task_entries = [e for e in entries if e["item_type"] == "task"]
        assert len(task_entries) == 1
        assert task_entries[0]["actor"] == "bot"

    def test_actor_on_create_epic(self, store, monkeypatch):
        monkeypatch.setenv("PROJECTMAN_ACTOR", "bot")
        store.create_epic("Epic", "Desc")
        entries = _read_log(store)
        epic_entries = [e for e in entries if e["item_type"] == "epic"]
        assert len(epic_entries) == 1
        assert epic_entries[0]["actor"] == "bot"

    def test_actor_on_update(self, store, monkeypatch):
        monkeypatch.setenv("PROJECTMAN_ACTOR", "bot")
        store.create_story("Story", "Desc")
        store.update("US-TST-1", status="active")
        entries = _read_log(store)
        update_entries = [e for e in entries if e["event_type"] == "update"]
        assert len(update_entries) == 1
        assert update_entries[0]["actor"] == "bot"

    def test_actor_on_archive(self, store, monkeypatch):
        monkeypatch.setenv("PROJECTMAN_ACTOR", "bot")
        store.create_story("Story", "Desc")
        store.archive("US-TST-1")
        entries = _read_log(store)
        # archive() delegates to update(), so the event_type is "update"
        update_entries = [e for e in entries if e["event_type"] == "update"]
        assert len(update_entries) == 1
        assert update_entries[0]["actor"] == "bot"
