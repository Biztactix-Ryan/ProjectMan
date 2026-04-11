# ProjectMan Bug Audit & Fixes

**Date:** 2026-04-11
**Status:** In Progress

---

## What It Does

ProjectMan is a git-native project management tool that stores stories, tasks, and epics as markdown files with YAML frontmatter in `.project/`. It provides:
- **MCP server** (stdio/SSE) for Claude Code integration
- **FastAPI web dashboard** (HTMX + Jinja2)
- **CLI** for direct commands
- **Hub mode** for multi-repo coordination via git submodules
- **Semantic search** via embeddings (SQLite + fastembed)
- **Activity logging** (JSONL append-only audit trail)

---

## Critical Bugs

### BUG 1: Cache Staleness — No Invalidation on External File Changes
**Severity: CRITICAL** | **File:** `store.py:21`

The caching system is a pure in-memory dict with no invalidation on external changes. If files are modified by anything other than the current Store instance, the cache serves stale data.

```python
_cache: dict[tuple[str, str], list[tuple]] = {}  # Never invalidated on external changes
```

**When this bites you:**
- `git pull` updates files → cache still holds old data
- Web UI and MCP server are separate processes with independent caches
- Direct filesystem edits bypass cache entirely

**Fix:** Add file watching or timestamp-based cache validation.

---

### BUG 2: `write_index()` Rebuilds Index from Cache (Not Disk)
**Severity: HIGH** | **File:** `indexer.py:353-355`

```python
def write_index(store: Store) -> None:
    epics = store.list_epics()     # READS FROM CACHE if populated
    stories = store.list_stories() # READS FROM CACHE if populated
    tasks = store.list_tasks()     # READS FROM CACHE if populated
```

If the cache is stale (Bug 1), `write_index()` writes a stale index to disk.

**Fix:** Invalidate cache before writing index, or read directly from disk for index building.

---

### BUG 3: Web API Creates New Store Per Request
**Severity: MEDIUM** | **File:** `web/routes/api.py:44-54`

```python
def get_store(project: Optional[str] = Query(None)) -> Store:
    ...
    return Store(root)  # NEW instance every call
```

Every API request gets a fresh Store instance. The module-level cache is shared, but this creates unnecessary object churn and makes cache debugging confusing.

**Fix:** Use a cached Store instance via `app.state`.

---

### BUG 4: `_cache_append` Only Appends to Existing Cache
**Severity: MEDIUM** | **File:** `store.py:364-370`

```python
def _cache_append(self, item_type: str, meta, body: str) -> None:
    key = self._cache_key(item_type)
    if key in _cache:
        _cache[key].append((meta, body))  # SILENTLY SKIPS if cache not populated
```

If `create_story()` is called but no `list_*()` was ever called, the new item won't be in cache. Self-heals on next `list_*()` call.

**Fix:** If cache doesn't exist, populate it.

---

### BUG 5: Embeddings Never Auto-Update
**Severity: MEDIUM** | **File:** `embeddings.py`, `store.py`

`EmbeddingStore.index_item()` is never called automatically. Only explicit `pm_reindex` command updates embeddings.

**Fix:** Call `EmbeddingStore.index_item()` in `store.update()` and `create_*()`.

---

### BUG 6: `_cache_stats["invalidations"]` Misused
**Severity: LOW** | **File:** `store.py:369-370`

Both `_cache_append` (which adds, not invalidates) and `_invalidate_cache` (which removes) both increment `invalidations`:

```python
# _cache_append increments "invalidations" — WRONG
_cache_stats["invalidations"] += 1
```

**Fix:** Use a separate counter for appends, or don't count appends as invalidations.

---

## Fix Priority Order

1. **BUG 2** — `write_index()` reading from stale cache → corrupts index.yaml
2. **BUG 1** — No cache invalidation on external changes → root cause of staleness
3. **BUG 5** — Embeddings not updating → search results go stale
4. **BUG 3** — Web API creating new Store per request → unnecessary churn
5. **BUG 4** — `_cache_append` silent failure → creates confusion
6. **BUG 6** — Cache stats misused → makes debugging hard

---

## What It Does Well

1. **Surgical cache updates** — `_cache_update_entry` does efficient in-place modifications
2. **Archived item handling** — archived items properly evicted from cache
3. **Rollback on cycle detection** — dependency validation properly rolls back on failure
4. **Append-only activity log** — JSONL format safe from corruption
5. **Git-native design** — data versionable alongside code
6. **Content-hash-based embedding updates** — skips re-embedding if content unchanged
7. **Hub multi-repo coordination** — properly handles submodules and cross-repo changesets
