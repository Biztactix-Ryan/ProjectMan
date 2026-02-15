"""HTML page routes (Jinja2 rendered)."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from projectman import __version__

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter()


def _ctx(active_page: str, **extra) -> dict:
    """Build common template context (without request — passed separately)."""
    return {
        "active_page": active_page,
        "version": __version__,
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", _ctx("dashboard"))


@router.get("/board", response_class=HTMLResponse)
def board(request: Request):
    return templates.TemplateResponse(request, "board.html", _ctx("board"))


@router.get("/epics", response_class=HTMLResponse)
def epics_list(request: Request):
    return templates.TemplateResponse(request, "epics.html", _ctx("epics"))


@router.get("/stories", response_class=HTMLResponse)
def stories_list(request: Request):
    return templates.TemplateResponse(request, "stories.html", _ctx("stories"))


@router.get("/project-docs", response_class=HTMLResponse)
def docs_list(request: Request):
    return templates.TemplateResponse(request, "docs.html", _ctx("docs"))


@router.get("/audit", response_class=HTMLResponse)
def audit_view(request: Request):
    return templates.TemplateResponse(request, "audit.html", _ctx("audit"))


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = ""):
    return templates.TemplateResponse(
        request, "search.html", _ctx("search", query=q)
    )


@router.get("/epics/{epic_id}", response_class=HTMLResponse)
def epic_detail(request: Request, epic_id: str):
    return templates.TemplateResponse(
        request, "epic_detail.html", _ctx("epics", epic_id=epic_id)
    )


@router.get("/stories/{story_id}", response_class=HTMLResponse)
def story_detail(request: Request, story_id: str):
    return templates.TemplateResponse(
        request, "story_detail.html", _ctx("stories", story_id=story_id)
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: str):
    return templates.TemplateResponse(
        request, "task_detail.html", _ctx("tasks", task_id=task_id)
    )
