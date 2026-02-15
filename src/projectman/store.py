"""CRUD operations for stories and tasks via python-frontmatter."""

from datetime import date
from pathlib import Path
from typing import Optional

import frontmatter

from .config import load_config, save_config
from .models import (
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

    def __init__(self, root: Path):
        self.root = root
        self.project_dir = root / ".project"
        self.stories_dir = self.project_dir / "stories"
        self.tasks_dir = self.project_dir / "tasks"
        self.epics_dir = self.project_dir / "epics"
        self.config = load_config(root)

    def _next_story_id(self) -> str:
        sid = f"US-{self.config.prefix}-{self.config.next_story_id}"
        self.config.next_story_id += 1
        save_config(self.config, self.root)
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
        save_config(self.config, self.root)
        return eid

    def _epic_path(self, epic_id: str) -> Path:
        return self.epics_dir / f"{epic_id}.md"

    def _is_epic_id(self, item_id: str) -> bool:
        return item_id.startswith("EPIC-")

    def _is_task_id(self, item_id: str) -> bool:
        """Task IDs have 3 parts (PREFIX-N-N), story IDs have 2 (PREFIX-N)."""
        parts = item_id.split("-")
        return len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit()

    def create_story(
        self,
        title: str,
        description: str,
        priority: Optional[str] = None,
        points: Optional[int] = None,
        tags: Optional[list[str]] = None,
    ) -> StoryFrontmatter:
        """Create a new story and write it to disk."""
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
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._story_path(story_id).write_text(frontmatter.dumps(post))
        return meta

    def get_story(self, story_id: str) -> tuple[StoryFrontmatter, str]:
        """Read a story, returning (frontmatter, body)."""
        path = self._story_path(story_id)
        if not path.exists():
            raise FileNotFoundError(f"Story not found: {story_id}")
        post = frontmatter.load(str(path))
        meta = StoryFrontmatter(**post.metadata)
        return meta, post.content

    def list_stories(
        self, status: Optional[str] = None
    ) -> list[StoryFrontmatter]:
        """List all stories, optionally filtered by status. Skips malformed files."""
        if not self.stories_dir.exists():
            return []
        stories = []
        for path in sorted(self.stories_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = StoryFrontmatter(**post.metadata)
                if status is None or meta.status.value == status:
                    stories.append(meta)
            except Exception:
                continue
        return stories

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
        return meta

    def get_epic(self, epic_id: str) -> tuple[EpicFrontmatter, str]:
        """Read an epic, returning (frontmatter, body)."""
        path = self._epic_path(epic_id)
        if not path.exists():
            raise FileNotFoundError(f"Epic not found: {epic_id}")
        post = frontmatter.load(str(path))
        meta = EpicFrontmatter(**post.metadata)
        return meta, post.content

    def list_epics(
        self, status: Optional[str] = None
    ) -> list[EpicFrontmatter]:
        """List all epics, optionally filtered by status. Skips malformed files."""
        if not self.epics_dir.exists():
            return []
        epics = []
        for path in sorted(self.epics_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = EpicFrontmatter(**post.metadata)
                if status is None or meta.status.value == status:
                    epics.append(meta)
            except Exception:
                continue
        return epics

    def create_task(
        self,
        story_id: str,
        title: str,
        description: str,
        points: Optional[int] = None,
    ) -> TaskFrontmatter:
        """Create a new task under a story."""
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        # Verify story exists
        if not self._story_path(story_id).exists():
            raise FileNotFoundError(f"Story not found: {story_id}")

        task_id = self._next_task_id(story_id)
        today = date.today()

        meta = TaskFrontmatter(
            id=task_id,
            story_id=story_id,
            title=title,
            status=TaskStatus.todo,
            points=points,
            created=today,
            updated=today,
        )

        post = frontmatter.Post(
            content=description,
            **meta.model_dump(mode="json"),
        )
        self._task_path(task_id).write_text(frontmatter.dumps(post))
        return meta

    def create_tasks(
        self,
        story_id: str,
        tasks: list[dict],
    ) -> list[TaskFrontmatter]:
        """Create multiple tasks under a story in a single call.

        Each entry in *tasks* should be a dict with keys ``title``,
        ``description``, and optionally ``points``.  Returns the list of
        created :class:`TaskFrontmatter` objects.
        """
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        if not self._story_path(story_id).exists():
            raise FileNotFoundError(f"Story not found: {story_id}")

        today = date.today()
        created: list[TaskFrontmatter] = []

        for entry in tasks:
            task_id = self._next_task_id(story_id)
            meta = TaskFrontmatter(
                id=task_id,
                story_id=story_id,
                title=entry["title"],
                status=TaskStatus.todo,
                points=entry.get("points"),
                created=today,
                updated=today,
            )
            post = frontmatter.Post(
                content=entry.get("description", ""),
                **meta.model_dump(mode="json"),
            )
            self._task_path(task_id).write_text(frontmatter.dumps(post))
            created.append(meta)

        return created

    def get_task(self, task_id: str) -> tuple[TaskFrontmatter, str]:
        """Read a task, returning (frontmatter, body)."""
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
        tasks = []
        for path in sorted(self.tasks_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                meta = TaskFrontmatter(**post.metadata)
                if story_id and meta.story_id != story_id:
                    continue
                if status and meta.status.value != status:
                    continue
                tasks.append(meta)
            except Exception:
                continue
        return tasks

    def update(self, item_id: str, **kwargs) -> EpicFrontmatter | StoryFrontmatter | TaskFrontmatter:
        """Update fields on an epic, story, or task."""
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
