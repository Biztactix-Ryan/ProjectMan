"""Pydantic models for ProjectMan data structures."""

import re
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator

FIBONACCI_POINTS = {1, 2, 3, 5, 8, 13}


class StoryStatus(str, Enum):
    backlog = "backlog"
    ready = "ready"
    active = "active"
    done = "done"
    archived = "archived"


class EpicStatus(str, Enum):
    draft = "draft"
    active = "active"
    done = "done"
    archived = "archived"


class TaskStatus(str, Enum):
    todo = "todo"
    in_progress = "in-progress"
    review = "review"
    done = "done"
    blocked = "blocked"


class Priority(str, Enum):
    must = "must"
    should = "should"
    could = "could"
    wont = "wont"


class StoryFrontmatter(BaseModel):
    id: str
    title: str
    status: StoryStatus = StoryStatus.backlog
    priority: Priority = Priority.should
    points: Optional[int] = None
    epic_id: Optional[str] = None
    tags: list[str] = []
    acceptance_criteria: list[str] = []
    created: date
    updated: date

    @field_validator("points")
    @classmethod
    def validate_fibonacci(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in FIBONACCI_POINTS:
            raise ValueError(
                f"Points must be fibonacci: {sorted(FIBONACCI_POINTS)}"
            )
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(f"Story ID must be alphanumeric with hyphens, got: {v}")
        return v


class EpicFrontmatter(BaseModel):
    id: str
    title: str
    status: EpicStatus = EpicStatus.draft
    priority: Priority = Priority.should
    points: Optional[int] = None
    target_date: Optional[date] = None
    tags: list[str] = []
    created: date
    updated: date

    @field_validator("points")
    @classmethod
    def validate_fibonacci(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in FIBONACCI_POINTS:
            raise ValueError(
                f"Points must be fibonacci: {sorted(FIBONACCI_POINTS)}"
            )
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(
                f"Epic ID must be alphanumeric with hyphens, got: {v}"
            )
        return v


class TaskFrontmatter(BaseModel):
    id: str
    story_id: str
    title: str
    status: TaskStatus = TaskStatus.todo
    points: Optional[int] = None
    assignee: Optional[str] = None
    created: date
    updated: date

    @field_validator("points")
    @classmethod
    def validate_fibonacci(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in FIBONACCI_POINTS:
            raise ValueError(
                f"Points must be fibonacci: {sorted(FIBONACCI_POINTS)}"
            )
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z][\w-]*$", v):
            raise ValueError(
                f"Task ID must be alphanumeric with hyphens, got: {v}"
            )
        return v


class ProjectConfig(BaseModel):
    name: str
    prefix: str = "PRJ"
    description: str = ""
    hub: bool = False
    next_story_id: int = 1
    next_epic_id: int = 1
    projects: list[str] = []

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        if not v.isalpha() or not v.isupper():
            raise ValueError("Prefix must be uppercase letters")
        return v


class IndexEntry(BaseModel):
    id: str
    title: str
    type: str  # "story", "task", or "epic"
    status: str
    points: Optional[int] = None
    story_id: Optional[str] = None
    epic_id: Optional[str] = None


class ProjectIndex(BaseModel):
    entries: list[IndexEntry] = []
    total_points: int = 0
    completed_points: int = 0
    story_count: int = 0
    task_count: int = 0
    epic_count: int = 0
