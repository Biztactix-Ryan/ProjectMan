"""Project configuration discovery and loading."""

from pathlib import Path
from typing import Optional

import yaml

from .models import ProjectConfig


def find_project_root(start: Optional[Path] = None) -> Path:
    """Walk up from start to find directory containing .project/config.yaml."""
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
