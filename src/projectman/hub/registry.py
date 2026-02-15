"""Hub registry — manage subproject registration via git submodules."""

import subprocess
from pathlib import Path
from typing import Optional

import yaml

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

    # Initialize .project/ in the submodule if it doesn't have one
    if not (target / ".project" / "config.yaml").exists():
        _init_subproject(target, name)

    # Register in config
    if name not in config.projects:
        config.projects.append(name)
        save_config(config, root)

    return f"added project '{name}' from {git_url}"


def _init_subproject(target: Path, name: str) -> None:
    """Initialize .project/ inside a submodule."""
    import yaml
    from jinja2 import Environment, FileSystemLoader

    # Derive a prefix from the project name (e.g. "my-api" -> "API", "webapp" -> "WEB")
    clean = name.replace("-", "").replace("_", "")
    prefix = clean[:3].upper() or "PRJ"

    proj = target / ".project"
    proj.mkdir(exist_ok=True)
    (proj / "stories").mkdir(exist_ok=True)
    (proj / "tasks").mkdir(exist_ok=True)

    # Try to render from templates, fall back to inline
    try:
        import importlib.resources
        tdir = str(importlib.resources.files("projectman") / "templates")
        env = Environment(loader=FileSystemLoader(tdir), keep_trailing_newline=True)
        ctx = dict(name=name, prefix=prefix, description="", hub=False)

        (proj / "config.yaml").write_text(env.get_template("config.yaml.j2").render(**ctx))
        (proj / "PROJECT.md").write_text(env.get_template("project.md.j2").render(**ctx))
        (proj / "INFRASTRUCTURE.md").write_text(env.get_template("infrastructure.md.j2").render(**ctx))
        (proj / "SECURITY.md").write_text(env.get_template("security.md.j2").render(**ctx))
    except Exception:
        # Minimal fallback if templates aren't available
        config_data = {
            "name": name,
            "prefix": prefix,
            "description": "",
            "hub": False,
            "next_story_id": 1,
            "projects": [],
        }
        (proj / "config.yaml").write_text(yaml.dump(config_data, default_flow_style=False))
        (proj / "PROJECT.md").write_text(f"# {name}\n\n## Architecture\n\n## Key Decisions\n")
        (proj / "INFRASTRUCTURE.md").write_text(f"# {name} — Infrastructure\n\n## Environments\n")
        (proj / "SECURITY.md").write_text(f"# {name} — Security\n\n## Authentication\n")

    # Write empty index
    empty_index = {
        "entries": [],
        "total_points": 0,
        "completed_points": 0,
        "story_count": 0,
        "task_count": 0,
    }
    (proj / "index.yaml").write_text(yaml.dump(empty_index, default_flow_style=False))


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
