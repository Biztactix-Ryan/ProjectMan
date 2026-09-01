"""Embedding-based semantic search using fastembed + SQLite."""

import hashlib
import os
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
        # Lazily-built in-memory view of the embeddings table.
        # _matrix: np.ndarray of shape (n, dim), _rows: parallel (id, title, type) tuples.
        self._matrix: Optional[np.ndarray] = None
        self._rows: Optional[list[tuple[str, str, str]]] = None
        # Staleness fingerprint of the db as of the last cache build (see
        # _fingerprint); None whenever the cache is empty.
        self._cache_stamp: Optional[tuple] = None
        # Long-lived read connection used for the staleness check. Kept open
        # so a warm search costs one prepared query instead of a fresh
        # sqlite3.connect(), and so PRAGMA data_version stays comparable
        # across calls (it only tracks commits from *other* connections).
        self._conn: Optional[sqlite3.Connection] = None
        self._conn_key: Optional[int] = None
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

    def _invalidate_cache(self):
        """Drop the cached vector matrix so the next search() rebuilds it.

        Covers writes made through this instance. Writes made by another
        process (or another EmbeddingStore in this one) are caught separately
        by the fingerprint check in _load_matrix().
        """
        self._matrix = None
        self._rows = None
        self._cache_stamp = None

    def _file_stat(self, path: Path) -> Optional[tuple[int, int, int]]:
        """(mtime_ns, size, inode) for path, or None when it does not exist."""
        try:
            st = os.stat(path)
        except (OSError, ValueError):
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def _read_connection(self) -> sqlite3.Connection:
        """Return the long-lived read connection, reopening it if the db file
        was replaced on disk (different inode) since it was opened."""
        stat = self._file_stat(self.db_path)
        key = None if stat is None else stat[2]
        if self._conn is not None and key != self._conn_key:
            self.close()
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn_key = key
        return self._conn

    def close(self):
        """Close the cached read connection (safe to call repeatedly)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
        self._conn = None
        self._conn_key = None

    # One round-trip that yields both staleness signals without touching the
    # vector column: the row count and SQLite's data_version counter.
    _FINGERPRINT_SQL = (
        "SELECT (SELECT COUNT(*) FROM embeddings), data_version FROM pragma_data_version"
    )

    def _fingerprint(self, conn) -> tuple:
        """Cheap staleness fingerprint of the embeddings database.

        Three signals, none of which reads the vector column (so a warm search
        stays O(1) in vector bytes):

        * ``PRAGMA data_version`` -- bumped on this connection whenever *any
          other* connection, in this process or another, commits to the
          database. This catches in-place UPDATEs that leave the row count and
          file size untouched, and does not depend on filesystem timestamp
          granularity.
        * ``SELECT COUNT(*)`` -- a journal-mode-independent fallback for
          inserts and deletes.
        * ``os.stat`` of the db file (mtime_ns, size, inode) -- catches the db
          file being swapped or rewritten underneath us.

        Limitation: writes committed on *this* connection would not move
        data_version, so index_item() and reindex_all() still call
        _invalidate_cache() directly; they write on their own connections
        anyway. A concurrent writer that changes a row and restores it before
        the next search is likewise indistinguishable from no change.
        """
        try:
            count, data_version = conn.execute(self._FINGERPRINT_SQL).fetchone()
        except sqlite3.Error:
            # Table missing (db recreated/truncated) -- force a rebuild.
            self._init_db()
            return ("unreadable", self._file_stat(self.db_path))
        return (self._file_stat(self.db_path), count, data_version)

    def _load_matrix(self) -> tuple[np.ndarray, list[tuple[str, str, str]]]:
        """Return the cached (matrix, rows) view, building it on first use.

        Every vector blob is decoded exactly once per cache build via a single
        np.frombuffer over the concatenated blobs -- never inside a query loop.

        A cached matrix is reused only while the database fingerprint (see
        _fingerprint) still matches, so rows written by another process or by
        a second EmbeddingStore on the same file are picked up automatically.

        Ordering matters: the fingerprint stored as self._cache_stamp is the
        one taken *before* the vector SELECT, never after it. Python's sqlite3
        runs bare SELECTs in autocommit mode (isolation_level="" only opens an
        implicit transaction for DML), so the fingerprint query and the vector
        SELECT are two separate read transactions and a commit from another
        connection can land between them. Recording the pre-read fingerprint
        is the conservative side of that race: a write that lands between the
        stamp and the SELECT is already present in the rows we loaded, and the
        now-outdated stamp merely triggers one redundant rebuild on the next
        search. Recording the post-read fingerprint would be unsafe -- it
        would describe a database state whose rows are missing from the matrix
        we just built, and the cache would serve stale results until some
        unrelated write moved the fingerprint again.

        We deliberately do *not* wrap the two reads in an explicit "BEGIN" ...
        "COMMIT" read transaction, which would give both statements one
        consistent snapshot: in SQLite's default rollback-journal mode a read
        transaction holds a SHARED lock for its whole duration, so it would
        block every writer for as long as the full matrix load takes. The
        pre-read stamp gets correctness without that cost.
        """
        conn = self._read_connection()
        stamp = self._fingerprint(conn)
        if (
            self._matrix is not None
            and self._rows is not None
            and self._cache_stamp == stamp
        ):
            return self._matrix, self._rows

        rows = conn.execute("SELECT id, title, type, vector FROM embeddings").fetchall()

        meta: list[tuple[str, str, str]] = []
        blobs: list[bytes] = []
        for row_id, title, item_type, blob in rows:
            if not blob:
                continue
            meta.append((row_id, title, item_type))
            blobs.append(blob)

        if not blobs:
            matrix = np.empty((0, 0), dtype=np.float32)
        else:
            dim = len(blobs[0]) // 4
            if any(len(b) != dim * 4 for b in blobs):
                raise ValueError("embeddings table contains vectors of differing dimensions")
            matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(blobs), dim)

        self._matrix = matrix
        self._rows = meta
        self._cache_stamp = stamp
        return matrix, meta

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
        self._invalidate_cache()

    def reindex_all(self, store):
        """Reindex all stories and tasks from the store."""
        for story in store.list_stories():
            _, body = store.get_story(story.id)
            content = self._build_content(body, story.tags)
            self.index_item(story.id, story.title, "story", content)

        for task in store.list_tasks():
            meta, body = store.get_task(task.id)
            content = self._build_content(body, meta.tags)
            self.index_item(task.id, task.title, "task", content)

        self._invalidate_cache()

    @staticmethod
    def _build_content(body: str, tags: list[str]) -> str:
        """Combine body text with tags for richer embedding content."""
        if tags:
            return f"{body} tags: {' '.join(tags)}"
        return body

    def search(self, query: str, top_k: int = 10) -> list[EmbeddingResult]:
        """Search by semantic similarity using cosine distance (normalized dot product).

        Scores are computed as a single matrix-vector product over the cached
        matrix, and the top_k rows are selected with np.argpartition -- no
        Python-level loop over the index. Ties resolve by row (insertion) order,
        matching the stable full-list sort this replaced.
        """
        matrix, rows = self._load_matrix()
        if not rows or top_k <= 0:
            return []

        query_vec = np.asarray(next(self.model.embed([query])), dtype=np.float32)

        # Cosine similarity for the whole index in one BLAS call (vectors are normalized)
        scores = matrix @ query_vec

        n = scores.shape[0]
        k = min(top_k, n)
        if k >= n:
            order = np.argsort(-scores, kind="stable")
        else:
            candidates = np.argpartition(-scores, k - 1)[:k]
            # argpartition leaves the candidates unordered; sort them by row index
            # first so the stable score sort below breaks ties by row order.
            candidates.sort()
            order = candidates[np.argsort(-scores[candidates], kind="stable")]

        return [
            EmbeddingResult(
                id=rows[i][0], title=rows[i][1], type=rows[i][2], score=float(scores[i])
            )
            for i in order
        ]
