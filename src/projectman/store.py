"""CRUD operations for stories and tasks via python-frontmatter."""

import copy
import logging
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

import yaml

logger = logging.getLogger(__name__)

# Module-level cache: keyed by (base_dir, item_type) where item_type is
# "stories", "tasks", or "epics".  Values are lists of (frontmatter, body)
# tuples.  Populated on first list call; get methods extract from here first.
_cache: dict[tuple[str, str], list[tuple]] = {}

# Cache statistics — only tracked when PROJECTMAN_CACHE_DEBUG is set.
_cache_stats: dict[str, int] = {"hits": 0, "misses": 0, "invalidations": 0}
_cache_debug: bool = bool(os.environ.get("PROJECTMAN_CACHE_DEBUG"))


def clear_all_caches() -> None:
    """Clear the entire module-level cache and reset stats."""
    _cache.clear()
    _cache_stats["hits"] = 0
    _cache_stats["misses"] = 0
    _cache_stats["invalidations"] = 0


def get_cache_stats() -> dict[str, int]:
    """Return a copy of the current cache statistics."""
    return dict(_cache_stats)

from .config import load_config
from .models import (
    ChangesetEntry,
    ChangesetFrontmatter,
    ChangesetStatus,
    EventType,
    ItemType,
    LogEntry,
    LogSource,
    ProjectConfig,
    EpicFrontmatter,
    EpicStatus,
    Priority,
    StoryFrontmatter,
    StoryStatus,
    TaskFrontmatter,
    TaskStatus,
)


class Store:
    """File-backed store for stories and tasks."""

    def __init__(self, root: Path, project_dir: Path | None = None):
        self.root = root
        self.project_dir = project_dir if project_dir is not None else (root / ".project")
        self.stories_dir = self.project_dir / "stories"
        self.tasks_dir = self.project_dir / "tasks"
        self.epics_dir = self.project_dir / "epics"
        self.config = load_config(root) if project_dir is None else self._load_config()

    def _load_config(self) -> ProjectConfig:
        """Load config.yaml from self.project_dir."""
        config_path = self.project_dir / "config.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return ProjectConfig(**data)

    def _save_config(self) -> None:
        """Save config.yaml to self.project_dir."""
        config_path = self.project_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(self.config.model_dump(), f, default_flow_style=False)

    def _next_story_id(self) -> str:
        sid = f"US-{self.config.prefix}-{self.config.next_story_id}"
        self.config.next_story_id += 1
        self._save_config()
        return sid

    def _next_task_id(self, story_id: str) -> str:
        existing = self.list_tasks(story_id=story_id)
        next_num = len(existing) + 1
        return f"{story_id}-{next_num}"

    def _story_path(self, story_id: str) -> Path:
        return self.stories_dir / f"{story_id}.md"

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.md"

    def _next_epic_id(self) -> str:
        eid = f"EPIC-{self.config.prefix}-{self.config.next_epic_id}"
        self.config.next_epic_id += 1
        self._save_config()
        return eid

    def _epic_path(self, epic_id: str) -> Path:
        return self.epics_dir / f"{epic_id}.md"

    def _is_epic_id(self, item_id: str) -> bool:
        return item_id.startswith("EPIC-")

    def _is_task_id(self, item_id: str) -> bool:
        """Task IDs have 3 parts (PREFIX-N-N), story IDs have 2 (PREFIX-N)."""
        parts = item_id.split("-")
        return len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit()

    def _auto_commit(self, files: list[Path], message: str) -> None:
        """Auto-commit specific files if auto_commit is enabled.

        Silently skips if git is not available, not in a repo, or commit fails.
        """
        if not self.config.auto_commit:
            return

        import subprocess

        try:
            str_files = [str(f) for f in files if f.exists()]
            if not str_files:
                return

            result = subprocess.run(
                ["git", "add", "--"] + str_files,
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("auto-commit: git add failed: %s", result.stderr.strip())
                return

            # Check if there's anything staged
            diff = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(self.root),
                capture_output=True,
            )
            if diff.returncode == 0:
                return  # nothing staged

            commit = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if commit.returncode != 0:
                logger.warning("auto-commit: commit failed: %s", commit.stderr.strip())
                return

            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if sha.returncode == 0:
                logger.debug("auto-commit: %s [%s]", message, sha.stdout.strip())
        except FileNotFoundError:
            logger.warning("auto-commit: git not found, skipping")
        except Exception as exc:
            logger.warning("auto-commit: unexpected error: %s", exc)

    def _resolve_actor(self) -> str:
        """Resolve the actor for activity log entries.

        Priority: PROJECTMAN_ACTOR env var > git config user.name > "unknown".
        """
        env_actor = os.environ.get("PROJECTMAN_ACTOR")
        if env_actor:
            return env_actor
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except FileNotFoundError:
            pass
        return "unknown"

    def _emit_log(
        self,
        event_type: EventType,
        item_id: str,
        item_type: ItemType,
        changes: dict | None = None,
    ) -> None:
        """Emit an activity log entry. Failures are silently swallowed."""
        from .activity_log import append_log_entry

        try:
            entry = LogEntry(
                event_type=event_type,
                item_id=item_id,
                item_type=item_type,
                changes=changes or {},
                timestamp=datetime.now(timezone.utc),
                actor=self._resolve_actor(),
                source=LogSource.cli,
            )
            log_path = self.project_dir / "activity.jsonl"
            append_log_entry(log_path, entry)
        except Exception:
            logger.debug("activity log: failed to emit %s for %s", event_type, item_id)

    def create_story(
        self,
        title: str,
        description: str,
        priority: Optional[str] = None,
        points: Optional[int] = None,
        tags: Optional[list[str]] = None,
        acceptance_criteria: Optional[list[str]] = None,
    ) -> tuple[StoryFrontmatter, list["TaskFrontmatter"]]:
        """Create a new story and write it to disk.

        Returns a tuple of (story_meta, auto_created_test_tasks).
        If *acceptance_criteria* are provided, a test task is created for each.
        """
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        story_id = self._next_story_id()
        today = date.today()

        meta = StoryFrontmatter(
            id=story_id,
            title=title,
            status=StoryStatus.backlog,
            priority=Priority(priority) if priority else Priority.should,
            points=points,
            tags=tags or [],
            acceptance_criteria=acceptance_criteria or [],
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._story_path(story_id).write_text(frontmatter.dumps(post))
        self._cache_append("stories", meta, description)
        self._emit_log(EventType.create, story_id, ItemType.story)

        # Auto-create test tasks for each acceptance criterion
        test_tasks: list[TaskFrontmatter] = []
        for criterion in (acceptance_criteria or []):
            task_title = f"Test: {criterion}"
            if len(task_title) > 120:
                task_title = task_title[:117] + "..."
            task_desc = (
                f"Verify acceptance criterion for story {story_id}:\n\n"
                f"> {criterion}"
            )
            task_meta = self.create_task(story_id, task_title, task_desc, _batch=True)
            test_tasks.append(task_meta)

        files = [self._story_path(story_id), self.project_dir / "config.yaml"]
        files.extend(self._task_path(t.id) for t in test_tasks)
        self._auto_commit(files, f"pm: create {story_id}")

        return meta, test_tasks

    def get_story(self, story_id: str) -> tuple[StoryFrontmatter, str]:
        """Read a story, returning (frontmatter, body). Uses cache if populated."""
        key = self._cache_key("stories")
        if key in _cache:
            for meta, body in _cache[key]:
                if meta.id == story_id:
                    if _cache_debug:
                        _cache_stats["hits"] += 1
                    return copy.deepcopy(meta), body
        path = self._story_path(story_id)
        if not path.exists():
            raise FileNotFoundError(f"Story not found: {story_id}")
        post = frontmatter.load(str(path))
        meta = StoryFrontmatter(**post.metadata)
        return meta, post.content

    def _cache_key(self, item_type: str) -> tuple[str, str]:
        """Return the cache key for a given item type."""
        return (str(self.project_dir), item_type)

    def _invalidate_cache(self, item_type: str) -> None:
        """Remove cached entries for the given item type."""
        if _cache.pop(self._cache_key(item_type), None) is not None and _cache_debug:
            _cache_stats["invalidations"] += 1

    def _cache_append(self, item_type: str, meta, body: str) -> None:
        """Append a new entry to the cache if it is populated."""
        key = self._cache_key(item_type)
        if key in _cache:
            _cache[key].append((meta, body))
            if _cache_debug:
                _cache_stats["invalidations"] += 1

    def _cache_update_entry(self, item_type: str, item_id: str, meta, body: str) -> None:
        """Replace a single entry in the cache if it is populated.

        If the item has transitioned to archived status, evict it from the
        cache instead of updating — archived items are excluded from the
        cache to bound memory usage.
        """
        key = self._cache_key(item_type)
        if key in _cache:
            # Check if item should be evicted (archived status)
            should_evict = (
                (item_type == "stories" and hasattr(meta, "status") and meta.status == StoryStatus.archived)
                or (item_type == "epics" and hasattr(meta, "status") and meta.status == EpicStatus.archived)
            )
            for i, (m, _) in enumerate(_cache[key]):
                if m.id == item_id:
                    if should_evict:
                        _cache[key].pop(i)
                    else:
                        _cache[key][i] = (meta, body)
                    if _cache_debug:
                        _cache_stats["invalidations"] += 1
                    return

    def clear_cache(self) -> None:
        """Clear all cached entries for this Store instance."""
        for item_type in ("stories", "tasks", "epics"):
            _cache.pop(self._cache_key(item_type), None)

    def _read_stories_from_disk(
        self, status_filter: Optional[str] = None
    ) -> list[tuple[StoryFrontmatter, str]]:
        """Read stories from disk, optionally filtered by status."""
        if not self.stories_dir.exists():
            return []
        entries = []
        for path in sorted(self.stories_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = StoryFrontmatter(**post.metadata)
                if status_filter and meta.status.value != status_filter:
                    continue
                entries.append((meta, post.content))
            except Exception:
                continue
        return entries

    def list_stories(
        self, status: Optional[str] = None
    ) -> list[StoryFrontmatter]:
        """List all stories, optionally filtered by status. Skips malformed files.

        Archived stories are excluded from the cache to bound memory usage.
        Requests for archived stories bypass the cache and read from disk.
        """
        if not self.stories_dir.exists():
            return []

        # Archived items bypass cache — read directly from disk
        if status == StoryStatus.archived.value:
            entries = self._read_stories_from_disk(status_filter=status)
            return copy.deepcopy([m for m, _ in entries])

        key = self._cache_key("stories")
        if key not in _cache:
            if _cache_debug:
                _cache_stats["misses"] += 1
            entries = []
            for path in sorted(self.stories_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(path))
                    meta = StoryFrontmatter(**post.metadata)
                    # Exclude archived items from cache to bound memory
                    if meta.status == StoryStatus.archived:
                        continue
                    entries.append((meta, post.content))
                except Exception:
                    continue
            _cache[key] = entries
        else:
            if _cache_debug:
                _cache_stats["hits"] += 1
        all_entries = _cache[key]
        if status is None:
            return copy.deepcopy([m for m, _ in all_entries])
        return copy.deepcopy([m for m, _ in all_entries if m.status.value == status])

    def create_epic(
        self,
        title: str,
        description: str,
        priority: Optional[str] = None,
        target_date: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> EpicFrontmatter:
        """Create a new epic and write it to disk."""
        self.epics_dir.mkdir(parents=True, exist_ok=True)
        epic_id = self._next_epic_id()
        today = date.today()

        meta = EpicFrontmatter(
            id=epic_id,
            title=title,
            status=EpicStatus.draft,
            priority=Priority(priority) if priority else Priority.should,
            target_date=target_date,
            tags=tags or [],
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._epic_path(epic_id).write_text(frontmatter.dumps(post))
        self._cache_append("epics", meta, description)
        self._emit_log(EventType.create, epic_id, ItemType.epic)

        self._auto_commit(
            [self._epic_path(epic_id), self.project_dir / "config.yaml"],
            f"pm: create {epic_id}",
        )

        return meta

    def get_epic(self, epic_id: str) -> tuple[EpicFrontmatter, str]:
        """Read an epic, returning (frontmatter, body). Uses cache if populated."""
        key = self._cache_key("epics")
        if key in _cache:
            for meta, body in _cache[key]:
                if meta.id == epic_id:
                    if _cache_debug:
                        _cache_stats["hits"] += 1
                    return copy.deepcopy(meta), body
        path = self._epic_path(epic_id)
        if not path.exists():
            raise FileNotFoundError(f"Epic not found: {epic_id}")
        post = frontmatter.load(str(path))
        meta = EpicFrontmatter(**post.metadata)
        return meta, post.content

    def _read_epics_from_disk(
        self, status_filter: Optional[str] = None
    ) -> list[tuple[EpicFrontmatter, str]]:
        """Read epics from disk, optionally filtered by status."""
        if not self.epics_dir.exists():
            return []
        entries = []
        for path in sorted(self.epics_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = EpicFrontmatter(**post.metadata)
                if status_filter and meta.status.value != status_filter:
                    continue
                entries.append((meta, post.content))
            except Exception:
                continue
        return entries

    def list_epics(
        self, status: Optional[str] = None
    ) -> list[EpicFrontmatter]:
        """List all epics, optionally filtered by status. Skips malformed files.

        Archived epics are excluded from the cache to bound memory usage.
        Requests for archived epics bypass the cache and read from disk.
        """
        if not self.epics_dir.exists():
            return []

        # Archived items bypass cache — read directly from disk
        if status == EpicStatus.archived.value:
            entries = self._read_epics_from_disk(status_filter=status)
            return copy.deepcopy([m for m, _ in entries])

        key = self._cache_key("epics")
        if key not in _cache:
            if _cache_debug:
                _cache_stats["misses"] += 1
            entries = []
            for path in sorted(self.epics_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(path))
                    meta = EpicFrontmatter(**post.metadata)
                    # Exclude archived items from cache to bound memory
                    if meta.status == EpicStatus.archived:
                        continue
                    entries.append((meta, post.content))
                except Exception:
                    continue
            _cache[key] = entries
        else:
            if _cache_debug:
                _cache_stats["hits"] += 1
        all_entries = _cache[key]
        if status is None:
            return copy.deepcopy([m for m, _ in all_entries])
        return copy.deepcopy([m for m, _ in all_entries if m.status.value == status])

    def _validate_depends_on(
        self, task_id: str, story_id: str, depends_on: list[str]
    ) -> None:
        """Validate depends_on entries: no self-ref, all must be siblings."""
        if not depends_on:
            return
        for dep in depends_on:
            if dep == task_id:
                raise ValueError(f"Task cannot depend on itself: {dep}")
            # Sibling check: dep must be a task under the same story
            dep_path = self._task_path(dep)
            if not dep_path.exists():
                raise ValueError(
                    f"Dependency {dep} does not exist"
                )
            dep_post = frontmatter.load(str(dep_path))
            dep_meta = TaskFrontmatter(**dep_post.metadata)
            if dep_meta.story_id != story_id:
                raise ValueError(
                    f"Dependency {dep} belongs to story {dep_meta.story_id}, "
                    f"not {story_id} — dependencies must be siblings"
                )

    def create_task(
        self,
        story_id: str,
        title: str,
        description: str,
        points: Optional[int] = None,
        tags: Optional[list[str]] = None,
        depends_on: Optional[list[str]] = None,
        *,
        _batch: bool = False,
    ) -> TaskFrontmatter:
        """Create a new task under a story."""
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        # Verify story exists
        if not self._story_path(story_id).exists():
            raise FileNotFoundError(f"Story not found: {story_id}")

        task_id = self._next_task_id(story_id)
        deps = depends_on or []

        self._validate_depends_on(task_id, story_id, deps)

        today = date.today()

        meta = TaskFrontmatter(
            id=task_id,
            story_id=story_id,
            title=title,
            status=TaskStatus.todo,
            points=points,
            tags=tags or [],
            depends_on=deps,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._task_path(task_id).write_text(frontmatter.dumps(post))
        self._cache_append("tasks", meta, description)
        self._emit_log(EventType.create, task_id, ItemType.task)

        if not _batch:
            self._auto_commit([self._task_path(task_id)], f"pm: create {task_id}")

        return meta

    def create_tasks(
        self,
        story_id: str,
        tasks: list[dict],
    ) -> list[TaskFrontmatter]:
        """Create multiple tasks under a story in a single call.

        Each entry in *tasks* should be a dict with keys ``title``,
        ``description``, and optionally ``points``, ``tags``, and
        ``depends_on``.  Returns the list of created
        :class:`TaskFrontmatter` objects.

        Dependencies are validated per-entry (self-ref, existence or
        intra-batch reference, sibling check) and a post-batch cycle
        check runs after all tasks are written.  On cycle detection the
        batch is rolled back.
        """
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        if not self._story_path(story_id).exists():
            raise FileNotFoundError(f"Story not found: {story_id}")

        # Pre-compute IDs for the entire batch so we can allow
        # forward references (task B depends on task C created later
        # in the same batch).
        batch_ids: list[str] = []
        cur = self._next_task_id(story_id)
        for i, _ in enumerate(tasks):
            if i == 0:
                batch_ids.append(cur)
            else:
                # Simulate sequential ID assignment.
                parts = cur.rsplit("-", 1)
                cur = f"{parts[0]}-{int(parts[1]) + 1}"
                batch_ids.append(cur)
        batch_id_set = set(batch_ids)

        today = date.today()
        created: list[TaskFrontmatter] = []

        for entry, task_id in zip(tasks, batch_ids):
            deps = entry.get("depends_on", [])

            # Validate deps: self-ref and non-batch deps via the
            # standard validator; batch-internal deps just need a
            # self-ref check (existence is guaranteed once we write).
            for dep in deps:
                if dep == task_id:
                    raise ValueError(f"Task cannot depend on itself: {dep}")
                if dep not in batch_id_set:
                    # Delegate to the standard validator for the single dep.
                    self._validate_depends_on(task_id, story_id, [dep])

            meta = TaskFrontmatter(
                id=task_id,
                story_id=story_id,
                title=entry["title"],
                status=TaskStatus.todo,
                points=entry.get("points"),
                tags=entry.get("tags", []),
                depends_on=deps,
                created=today,
                updated=today,
            )
            post = frontmatter.Post(
                content=entry.get("description", ""),
                **meta.model_dump(mode="json"),
            )
            self._task_path(task_id).write_text(frontmatter.dumps(post))
            self._cache_append("tasks", meta, entry.get("description", ""))
            self._emit_log(EventType.create, task_id, ItemType.task)
            created.append(meta)

        # Post-batch cycle check — rollback on failure.
        if created:
            try:
                self._check_dependency_cycles(story_id)
            except ValueError:
                for task in created:
                    self._task_path(task.id).unlink(missing_ok=True)
                self._invalidate_cache("tasks")
                raise

            files = [self._task_path(t.id) for t in created]
            self._auto_commit(files, f"pm: create {len(created)} tasks under {story_id}")

        return created

    def _check_dependency_cycles(self, story_id: str) -> None:
        """Detect dependency cycles among all tasks in a story via DFS."""
        all_tasks = self.list_tasks(story_id=story_id)
        graph: dict[str, list[str]] = {t.id: list(t.depends_on) for t in all_tasks}

        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node: str) -> None:
            visited.add(node)
            in_stack.add(node)
            for dep in graph.get(node, []):
                if dep in in_stack:
                    raise ValueError(
                        f"Dependency cycle detected: {node} -> {dep}"
                    )
                if dep not in visited:
                    dfs(dep)
            in_stack.discard(node)

        for node in graph:
            if node not in visited:
                dfs(node)

    def get_task(self, task_id: str) -> tuple[TaskFrontmatter, str]:
        """Read a task, returning (frontmatter, body). Uses cache if populated."""
        key = self._cache_key("tasks")
        if key in _cache:
            for meta, body in _cache[key]:
                if meta.id == task_id:
                    if _cache_debug:
                        _cache_stats["hits"] += 1
                    return copy.deepcopy(meta), body
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        post = frontmatter.load(str(path))
        meta = TaskFrontmatter(**post.metadata)
        return meta, post.content

    def list_tasks(
        self,
        story_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[TaskFrontmatter]:
        """List tasks, optionally filtered by story and/or status. Skips malformed files."""
        if not self.tasks_dir.exists():
            return []
        key = self._cache_key("tasks")
        if key not in _cache:
            if _cache_debug:
                _cache_stats["misses"] += 1
            entries = []
            for path in sorted(self.tasks_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(path))
                    meta = TaskFrontmatter(**post.metadata)
                    entries.append((meta, post.content))
                except Exception:
                    continue
            _cache[key] = entries
        else:
            if _cache_debug:
                _cache_stats["hits"] += 1
        all_entries = _cache[key]
        result = all_entries
        if story_id:
            result = [(m, b) for m, b in result if m.story_id == story_id]
        if status:
            result = [(m, b) for m, b in result if m.status.value == status]
        return copy.deepcopy([m for m, _ in result])

    def update(self, item_id: str, **kwargs) -> EpicFrontmatter | StoryFrontmatter | TaskFrontmatter:
        """Update fields on an epic, story, or task.

        Accepts frontmatter fields as keyword arguments.  The special
        ``body`` kwarg replaces the markdown body content (not frontmatter).
        """
        is_epic = self._is_epic_id(item_id)
        is_task = not is_epic and self._is_task_id(item_id)

        if is_epic:
            path = self._epic_path(item_id)
        elif is_task:
            path = self._task_path(item_id)
        else:
            path = self._story_path(item_id)

        if not path.exists():
            raise FileNotFoundError(f"Item not found: {item_id}")

        post = frontmatter.load(str(path))

        # Capture before-state for activity log diffs
        old_body = post.content
        old_meta = dict(post.metadata)

        # Capture field info for auto-commit message before modifying kwargs
        commit_parts = []
        for k, v in kwargs.items():
            if v is not None:
                commit_parts.append(f"{k}={v}" if k != "body" else "body")

        # Handle body separately — it replaces markdown content, not metadata
        new_body = kwargs.pop("body", None)
        if new_body is not None:
            post.content = new_body

        # Validate depends_on before applying to task
        new_depends_on = kwargs.get("depends_on")
        if new_depends_on is not None and is_task:
            story_id = post.metadata.get("story_id", "")
            self._validate_depends_on(item_id, story_id, new_depends_on)

        for key, value in kwargs.items():
            if value is not None:
                post.metadata[key] = value
        post.metadata["updated"] = date.today().isoformat()

        if is_epic:
            meta = EpicFrontmatter(**post.metadata)
        elif is_task:
            meta = TaskFrontmatter(**post.metadata)
        else:
            meta = StoryFrontmatter(**post.metadata)

        path.write_text(frontmatter.dumps(post))

        # Surgically update relevant cache entry
        if is_epic:
            self._cache_update_entry("epics", item_id, meta, post.content)
        elif is_task:
            self._cache_update_entry("tasks", item_id, meta, post.content)
        else:
            self._cache_update_entry("stories", item_id, meta, post.content)

        # Check for dependency cycles after writing the update
        if new_depends_on is not None and is_task:
            story_id = post.metadata.get("story_id", "")
            try:
                self._check_dependency_cycles(story_id)
            except ValueError:
                # Roll back: restore the original file
                post.metadata = {**old_meta, "updated": date.today().isoformat()}
                post.content = old_body
                path.write_text(frontmatter.dumps(post))
                self._invalidate_cache("tasks")
                raise

        # Build before/after field diffs for activity log
        changes: dict[str, dict] = {}
        for key, value in kwargs.items():
            if value is not None:
                before = old_meta.get(key)
                # Normalize enums/dates to strings for comparison
                before_str = str(before) if before is not None else None
                after_str = str(value)
                if before_str != after_str:
                    changes[key] = {"before": before, "after": value}
        if new_body is not None and new_body != old_body:
            changes["body"] = {"before": old_body, "after": new_body}

        item_type = ItemType.epic if is_epic else (ItemType.task if is_task else ItemType.story)
        self._emit_log(EventType.update, item_id, item_type, changes=changes)

        suffix = " ".join(commit_parts)
        msg = f"pm: update {item_id}" + (f" {suffix}" if suffix else "")
        self._auto_commit([path], msg)

        return meta

    def archive(self, item_id: str) -> None:
        """Archive an epic, story, or task."""
        if self._is_epic_id(item_id):
            self.update(item_id, status=EpicStatus.archived.value)
        elif self._is_task_id(item_id):
            self.update(item_id, status=TaskStatus.done.value)
        else:
            self.update(item_id, status=StoryStatus.archived.value)

    def get(self, item_id: str) -> tuple[EpicFrontmatter | StoryFrontmatter | TaskFrontmatter, str]:
        """Unified lookup by ID — dispatches to get_epic, get_story, or get_task."""
        if self._is_epic_id(item_id):
            return self.get_epic(item_id)
        if self._is_task_id(item_id):
            return self.get_task(item_id)
        return self.get_story(item_id)

    # ─── Changesets ───────────────────────────────────────────────

    @property
    def changesets_dir(self) -> Path:
        return self.project_dir / "changesets"

    def _next_changeset_id(self) -> str:
        cid = f"CS-{self.config.prefix}-{self.config.next_changeset_id}"
        self.config.next_changeset_id += 1
        self._save_config()
        return cid

    def _changeset_path(self, changeset_id: str) -> Path:
        return self.changesets_dir / f"{changeset_id}.md"

    def create_changeset(
        self,
        title: str,
        projects: list[str],
        description: str = "",
    ) -> ChangesetFrontmatter:
        """Create a changeset grouping changes across multiple projects."""
        self.changesets_dir.mkdir(parents=True, exist_ok=True)
        changeset_id = self._next_changeset_id()
        today = date.today()

        entries = [ChangesetEntry(project=p) for p in projects]

        meta = ChangesetFrontmatter(
            id=changeset_id,
            title=title,
            status=ChangesetStatus.open,
            entries=entries,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._changeset_path(changeset_id).write_text(frontmatter.dumps(post))
        self._emit_log(EventType.create, changeset_id, ItemType.changeset)
        return meta

    def get_changeset(self, changeset_id: str) -> tuple[ChangesetFrontmatter, str]:
        """Read a changeset, returning (frontmatter, body)."""
        path = self._changeset_path(changeset_id)
        if not path.exists():
            raise FileNotFoundError(f"Changeset not found: {changeset_id}")
        post = frontmatter.load(str(path))
        meta = ChangesetFrontmatter(**post.metadata)
        return meta, post.content

    def list_changesets(
        self, status: Optional[str] = None
    ) -> list[ChangesetFrontmatter]:
        """List all changesets, optionally filtered by status."""
        if not self.changesets_dir.exists():
            return []
        changesets = []
        for path in sorted(self.changesets_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = ChangesetFrontmatter(**post.metadata)
                if status is None or meta.status.value == status:
                    changesets.append(meta)
            except Exception:
                continue
        return changesets

    def add_changeset_entry(
        self, changeset_id: str, project: str, ref: str = ""
    ) -> ChangesetFrontmatter:
        """Add a project entry to an existing changeset."""
        meta, body = self.get_changeset(changeset_id)
        meta.entries.append(ChangesetEntry(project=project, ref=ref))
        meta.updated = date.today()

        post = frontmatter.Post(
            content=body,
            **meta.model_dump(mode="json"),
        )
        self._changeset_path(changeset_id).write_text(frontmatter.dumps(post))
        return meta

    # ─── Git Operations ──────────────────────────────────────────

    def commit_project_changes(self, message: Optional[str] = None) -> dict:
        """Stage and commit .project/ changes with an auto-generated message.

        If *message* is provided it is used as-is; otherwise a summary is
        generated from the staged diff (e.g. "pm: add 2 stories, update 1 task").

        Returns a dict with ``commit_hash``, ``message``, and ``files_changed``.
        Raises ``RuntimeError`` if the commit fails or there are no changes.
        """
        import subprocess

        project_dir = str(self.project_dir)

        # Stage all .project/ changes
        subprocess.run(
            ["git", "add", project_dir],
            cwd=str(self.root),
            capture_output=True,
            check=True,
        )

        # Check if there are staged changes
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", project_dir],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )

        changed_files = [f for f in diff_result.stdout.strip().splitlines() if f]
        if not changed_files:
            raise RuntimeError("No .project/ changes to commit")

        # Auto-generate message if not provided
        if message is None:
            message = self._generate_commit_message(changed_files)

        # Commit
        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )

        # Extract commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )
        commit_hash = hash_result.stdout.strip()

        return {
            "commit_hash": commit_hash,
            "message": message,
            "files_changed": changed_files,
        }

    def _generate_commit_message(self, changed_files: list[str]) -> str:
        """Generate a commit message summarizing .project/ changes."""
        stories_added = 0
        stories_updated = 0
        tasks_added = 0
        tasks_updated = 0
        epics_added = 0
        epics_updated = 0
        config_changed = False
        other = 0

        for f in changed_files:
            name = Path(f).name
            if "/stories/" in f or f.startswith("stories/"):
                # Heuristic: new files are "added", modified are "updated"
                # We can't easily distinguish from file list alone, so count all
                stories_updated += 1
            elif "/tasks/" in f or f.startswith("tasks/"):
                tasks_updated += 1
            elif "/epics/" in f or f.startswith("epics/"):
                epics_updated += 1
            elif name == "config.yaml" or name == "index.yaml":
                config_changed = True
            else:
                other += 1

        parts = []
        if stories_updated:
            parts.append(f"{stories_updated} {'story' if stories_updated == 1 else 'stories'}")
        if tasks_updated:
            parts.append(f"{tasks_updated} {'task' if tasks_updated == 1 else 'tasks'}")
        if epics_updated:
            parts.append(f"{epics_updated} {'epic' if epics_updated == 1 else 'epics'}")
        if config_changed:
            parts.append("config")
        if other:
            parts.append(f"{other} {'file' if other == 1 else 'files'}")

        if parts:
            return f"pm: update {', '.join(parts)}"
        return "pm: update project data"

    def push_project_changes(self, remote: str = "origin") -> dict:
        """Push committed changes to the remote.

        Validates that we are on a branch (not detached HEAD) and that
        the remote exists before pushing.

        Returns a dict with ``branch`` and ``remote`` on success,
        or ``up_to_date`` if there was nothing new to push.
        Raises ``RuntimeError`` on validation or push failure.
        """
        import subprocess

        # Check we're on a branch (not detached HEAD)
        branch_result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        if branch_result.returncode != 0:
            raise RuntimeError("Cannot push from a detached HEAD state — checkout a branch first")

        branch = branch_result.stdout.strip()

        # Validate remote exists
        remote_result = subprocess.run(
            ["git", "remote"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )
        remotes = [r.strip() for r in remote_result.stdout.strip().splitlines() if r.strip()]
        if remote not in remotes:
            raise RuntimeError(f"Remote '{remote}' not configured (available: {', '.join(remotes) or 'none'})")

        # Push
        push_result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        if push_result.returncode != 0:
            stderr = push_result.stderr.strip()
            raise RuntimeError(f"Push failed: {stderr}")

        return {
            "branch": branch,
            "remote": remote,
        }
