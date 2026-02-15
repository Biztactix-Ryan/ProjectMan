"""FastAPI application for ProjectMan Web UI."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from projectman import __version__
from projectman.config import find_project_root
from projectman.store import Store
from projectman.web.routes import api, pages

_WEB_DIR = Path(__file__).parent

app = FastAPI(title="ProjectMan Web", version=__version__)

app.include_router(api.router)
app.include_router(pages.router)


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")

templates = Jinja2Templates(directory=_WEB_DIR / "templates")


@app.on_event("startup")
def _startup() -> None:
    root = find_project_root()
    app.state.root = root
    app.state.store = Store(root)


def get_store() -> Store:
    """Dependency: return the Store instance."""
    return app.state.store


def get_root() -> Path:
    """Dependency: return the resolved project root."""
    return app.state.root


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
