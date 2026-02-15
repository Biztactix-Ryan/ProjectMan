"""Pydantic request/response schemas for the REST API."""

from datetime import date
from typing import Optional

from pydantic import BaseModel

from projectman.models import FIBONACCI_POINTS


# ─── Request Schemas ─────────────────────────────────────────────


class CreateEpicRequest(BaseModel):
    title: str
    description: str
    priority: Optional[str] = None
    target_date: Optional[str] = None
    tags: Optional[list[str]] = None


class CreateStoryRequest(BaseModel):
    title: str
    description: str
    priority: Optional[str] = None
    points: Optional[int] = None
    epic_id: Optional[str] = None


class CreateTaskRequest(BaseModel):
    story_id: str
    title: str
    description: str
    points: Optional[int] = None


class UpdateItemRequest(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    points: Optional[int] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    epic_id: Optional[str] = None


class GrabTaskRequest(BaseModel):
    assignee: str = "claude"


class UpdateDocRequest(BaseModel):
    content: str


# ─── Response Schemas ────────────────────────────────────────────


class EpicResponse(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    points: Optional[int] = None
    target_date: Optional[date] = None
    tags: list[str] = []
    created: date
    updated: date
    body: Optional[str] = None


class StoryResponse(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    points: Optional[int] = None
    epic_id: Optional[str] = None
    tags: list[str] = []
    created: date
    updated: date
    body: Optional[str] = None
    tasks: Optional[list["TaskResponse"]] = None


class TaskResponse(BaseModel):
    id: str
    story_id: str
    title: str
    status: str
    points: Optional[int] = None
    assignee: Optional[str] = None
    created: date
    updated: date
    body: Optional[str] = None


class StatusResponse(BaseModel):
    project: str
    epics: int
    stories: int
    tasks: int
    total_points: int
    completed_points: int
    completion: str
    by_status: dict[str, int]


class BurndownResponse(BaseModel):
    project: str
    total_points: int
    completed_points: int
    remaining_points: int
    completion: str


class RollupResponse(BaseModel):
    story_count: int
    total_points: int
    completed_points: int
    completion: str


class EpicDetailResponse(BaseModel):
    epic: EpicResponse
    body: str
    stories: list[dict]
    rollup: RollupResponse
