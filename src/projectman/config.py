"""Project configuration discovery and loading."""

import os
from pathlib import Path
from typing import Optional

import yaml

from .models import ProjectConfig


def find_project_root(start: Optional[Path] = None) -> Path:
    """Find the directory containing .project/config.yaml.

    Resolution order: explicit start > PROJECTMAN_ROOT env var > walk up
    from cwd. The env var pins the root for long-lived processes (e.g. a
    globally-registered MCP server) regardless of where they were spawned.
    """
    if start is None:
        env_root = os.environ.get("PROJECTMAN_ROOT")
        if env_root:
            candidate = Path(env_root).resolve()
            if (candidate / ".project" / "config.yaml").exists():
                return candidate
            raise FileNotFoundError(
                f"PROJECTMAN_ROOT is set to {env_root} but no .project/config.yaml exists there"
            )
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".project" / "config.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "No .project/config.yaml found in any parent directory"
            )
        current = parent


def project_dir(root: Optional[Path] = None) -> Path:
    """Return the .project/ directory path."""
    if root is None:
        root = find_project_root()
    return root / ".project"


def load_config(root: Optional[Path] = None) -> ProjectConfig:
    """Load and parse .project/config.yaml."""
    pdir = project_dir(root)
    config_path = pdir / "config.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return ProjectConfig(**data)


def save_config(config: ProjectConfig, root: Optional[Path] = None) -> None:
    """Save config back to disk."""
    pdir = project_dir(root)
    config_path = pdir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False)
