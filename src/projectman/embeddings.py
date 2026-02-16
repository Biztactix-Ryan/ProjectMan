"""Embedding-based semantic search using fastembed + SQLite."""

import hashlib
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class EmbeddingResult:
    id: str
    title: str
    type: str
    score: float


class EmbeddingStore:
    """SQLite-backed vector store for semantic search."""

    def __init__(self, project_dir: Path):
        self.db_path = project_dir / "embeddings.db"
        self._model = None
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                title TEXT,
                type TEXT,
                vector BLOB,
                content_hash TEXT
            )
        """)
        conn.commit()
        conn.close()

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        return self._model

    def _content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _encode_vector(self, vector) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    def _decode_vector(self, blob: bytes) -> list[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))

    def index_item(self, item_id: str, title: str, item_type: str, content: str):
        """Index a single item. Skips if content_hash unchanged."""
        text = f"{title} {content}"
        content_hash = self._content_hash(text)

        conn = sqlite3.connect(str(self.db_path))
        existing = conn.execute(
            "SELECT content_hash FROM embeddings WHERE id = ?", (item_id,)
        ).fetchone()

        if existing and existing[0] == content_hash:
            conn.close()
            return  # No change

        vector = next(self.model.embed([text]))
        blob = self._encode_vector(vector)

        conn.execute(
            "INSERT OR REPLACE INTO embeddings (id, title, type, vector, content_hash) VALUES (?, ?, ?, ?, ?)",
            (item_id, title, item_type, blob, content_hash),
        )
        conn.commit()
        conn.close()

    def reindex_all(self, store):
        """Reindex all stories and tasks from the store."""
        for story in store.list_stories():
            _, body = store.get_story(story.id)
            self.index_item(story.id, story.title, "story", body)

        for task in store.list_tasks():
            _, body = store.get_task(task.id)
            self.index_item(task.id, task.title, "task", body)

    def search(self, query: str, top_k: int = 10) -> list[EmbeddingResult]:
        """Search by semantic similarity using cosine distance (normalized dot product)."""
        query_vec = next(self.model.embed([query]))

        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT id, title, type, vector FROM embeddings").fetchall()
        conn.close()

        results = []
        for row_id, title, item_type, blob in rows:
            stored_vec = self._decode_vector(blob)
            # Cosine similarity via dot product (vectors are normalized)
            score = np.dot(query_vec, stored_vec)
            results.append(EmbeddingResult(
                id=row_id, title=title, type=item_type, score=float(score)
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
