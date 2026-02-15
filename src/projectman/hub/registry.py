"""Hub registry — manage subproject registration via git submodules."""

import subprocess
from pathlib import Path
from typing import Optional

from ..config import load_config, save_config


def add_project(name: str, git_url: str, root: Optional[Path] = None) -> str:
    """Register a project in the hub via git submodule add."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project — run 'projectman init --hub' first"

    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)

    target = projects_dir / name
    if target.exists():
        return f"error: project '{name}' already exists"

    # Add as git submodule
    try:
        subprocess.run(
            ["git", "submodule", "add", git_url, f"projects/{name}"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        return f"error adding submodule: {e.stderr}"
    except FileNotFoundError:
        return "error: git is not installed or not on PATH"

    # Register in config
    if name not in config.projects:
        config.projects.append(name)
        save_config(config, root)

    return f"added project '{name}' from {git_url}"


def list_projects(root: Optional[Path] = None) -> list[dict]:
    """List all registered projects with their status."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    results = []
    for name in config.projects:
        project_path = root / "projects" / name
        has_project_dir = (project_path / ".project").exists()
        results.append({
            "name": name,
            "path": str(project_path),
            "exists": project_path.exists(),
            "initialized": has_project_dir,
        })

    return results
