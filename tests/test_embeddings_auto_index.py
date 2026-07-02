"""Tests for embedding auto-indexing (BUG 5 fix)."""

import pytest
from unittest.mock import patch, MagicMock

from projectman.store import Store, clear_all_caches


class TestIndexEmbedding:
    """Tests for _index_embedding helper and its integration."""

    def test_index_embedding_is_called_on_create_story(self, store):
        """create_story calls _index_embedding with story type."""
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.create_story("My Story", "Description")
            mock_index.assert_called_once()
            call_args = mock_index.call_args
            assert call_args[0][1] == "My Story"  # title
            assert call_args[0][2] == "story"  # type
            assert call_args[0][3] == "Description"  # body

    def test_index_embedding_is_called_on_create_task(self, store):
        """create_task calls _index_embedding with task type."""
        store.create_story("Story", "Desc")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.create_task("US-TST-1", "My Task", "Task description")
            mock_index.assert_called_once()
            call_args = mock_index.call_args
            assert call_args[0][1] == "My Task"
            assert call_args[0][2] == "task"
            assert call_args[0][3] == "Task description"

    def test_index_embedding_is_called_on_update_story(self, store):
        """update() calls _index_embedding for stories."""
        store.create_story("My Story", "Original body")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.update("US-TST-1", title="Updated Title", body="Updated body")
            mock_index.assert_called_once()
            call_args = mock_index.call_args
            assert call_args[0][0] == "US-TST-1"
            assert call_args[0][1] == "Updated Title"
            assert call_args[0][2] == "story"
            assert call_args[0][3] == "Updated body"

    def test_index_embedding_is_called_on_update_task(self, store):
        """update() calls _index_embedding for tasks."""
        store.create_story("Story", "Desc")
        store.create_task("US-TST-1", "Task", "Original body")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.update("US-TST-1-1", body="Updated task body", status="in-progress")
            mock_index.assert_called_once()
            call_args = mock_index.call_args
            assert call_args[0][0] == "US-TST-1-1"
            assert call_args[0][2] == "task"
            assert call_args[0][3] == "Updated task body"

    def test_index_embedding_not_called_for_epic(self, store):
        """_index_embedding is not called for epics (epics are not indexed)."""
        store.create_epic("My Epic", "Epic description")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.update("EPIC-TST-1", title="Updated Epic")
            mock_index.assert_not_called()

    def test_index_embedding_silently_skips_on_import_error(self, store):
        """If fastembed is not installed, _index_embedding fails silently."""
        store.create_story("Story", "Desc")
        # Should not raise even if fastembed is not available
        store._index_embedding("US-TST-1", "Title", "story", "body")

    def test_index_embedding_silently_skips_on_embed_store_error(self, store):
        """If EmbeddingStore raises, _index_embedding catches and ignores it."""
        import sys
        import types

        store.create_story("Story", "Desc")

        # Inject a fake embeddings module whose EmbeddingStore raises. This keeps
        # the test independent of the optional embedding deps (numpy/fastembed),
        # which are not installed in CI. _index_embedding does a lazy
        # ``from .embeddings import EmbeddingStore``, so it picks up the fake.
        fake_embeddings = types.ModuleType("projectman.embeddings")

        def _raise(*args, **kwargs):
            raise Exception("DB error")

        fake_embeddings.EmbeddingStore = _raise

        with patch.dict(sys.modules, {"projectman.embeddings": fake_embeddings}):
            # Should not raise
            store._index_embedding("US-TST-1", "Title", "story", "body")

    def test_index_embedding_not_called_on_archive(self, store):
        """archive() calls update() but _index_embedding should still fire for stories."""
        store.create_story("Story", "Desc")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.archive("US-TST-1")  # archives via update
            # archive calls update internally, so embedding should be called
            mock_index.assert_called_once()

    def test_index_embedding_uses_current_title_and_body(self, store):
        """_index_embedding uses the current title and body, not stale values."""
        store.create_story("Original Title", "Original body")
        with patch.object(store, "_index_embedding", autospec=True) as mock_index:
            store.update("US-TST-1", title="New Title", body="New body")
            call_args = mock_index.call_args
            assert call_args[0][1] == "New Title"
            assert call_args[0][3] == "New body"
