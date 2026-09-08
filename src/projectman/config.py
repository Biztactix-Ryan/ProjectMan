"""Project configuration discovery and loading."""

import os
import sys
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


#: Parsed configs, keyed by the resolved absolute project root.  Each value
#: is ``(stamp, config)`` where ``stamp`` is the ``(st_mtime_ns, st_size)`` of
#: the ``config.yaml`` the config was parsed from.  Without this, every call
#: that needs the config is a fresh open + YAML parse.
_CONFIG_CACHE: dict[str, tuple[tuple[int, int], ProjectConfig]] = {}


def _config_stamp(config_path: Path) -> Optional[tuple[int, int]]:
    """Return the (mtime_ns, size) fingerprint of config.yaml, or None.

    None means the file could not be stat'd (missing, or unreadable), in
    which case the caller neither trusts nor fills the cache and lets the
    subsequent open() raise as it always has.
    """
    try:
        st = config_path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def clear_config_cache(root: Optional[Path] = None) -> None:
    """Drop cached config(s).

    With no argument the whole cache is dropped; with ``root`` only that
    project's entry goes.  Writers that rewrite config.yaml themselves call
    this so the next read is guaranteed fresh, rather than relying on the
    mtime check alone.
    """
    if root is None:
        _CONFIG_CACHE.clear()
    else:
        _CONFIG_CACHE.pop(str(Path(root).resolve()), None)


#: Keys older config.yaml files carry that no longer map to a field.  Hub
#: mode is gone (EPIC-PM-6), but checkouts predating its removal still have
#: these two lines on disk and must keep loading.
LEGACY_CONFIG_KEYS = ("hub", "projects")


def _drop_legacy_keys(data: dict, config_path: Path) -> dict:
    """Strip retired keys from raw config data, warning once per load."""
    if not isinstance(data, dict):
        return data
    stale = [key for key in LEGACY_CONFIG_KEYS if key in data]
    if not stale:
        return data
    print(
        f"projectman: ignoring retired config key(s) {', '.join(stale)} "
        f"in {config_path} (hub mode was removed)",
        file=sys.stderr,
    )
    return {key: value for key, value in data.items() if key not in stale}


def load_config(root: Optional[Path] = None) -> ProjectConfig:
    """Load and parse .project/config.yaml.

    The parsed config is cached per project root and reused while
    config.yaml's mtime and size are unchanged.  That keeps a hand-edit of
    config.yaml (flipping a ``tools:`` flag, say) visible to a long-lived
    MCP server on its very next call, which a plain in-process cache would
    not — the mtime check stands in for a TTL.

    The cached ``ProjectConfig`` instance is shared between callers, so a
    caller that mutates one (``Store`` bumping ``next_story_id``) should
    write it back with ``save_config``/``Store._save_config`` promptly.
    """
    if root is None:
        root = find_project_root()
    root = Path(root).resolve()
    config_path = project_dir(root) / "config.yaml"

    stamp = _config_stamp(config_path)
    if stamp is not None:
        cached = _CONFIG_CACHE.get(str(root))
        if cached is not None and cached[0] == stamp:
            return cached[1]

    with open(config_path) as f:
        data = yaml.safe_load(f)
    data = _drop_legacy_keys(data, config_path)
    config = ProjectConfig(**data)
    if stamp is not None:
        _CONFIG_CACHE[str(root)] = (stamp, config)
    return config


#: The tool families that are registered only on request, and the config key
#: that turns each one on.  ``server.TOOL_FAMILIES`` names the tools in each.
GATED_TOOL_FAMILIES = ("maintenance", "web")


def enabled_tool_families(config: Optional[ProjectConfig]) -> dict[str, bool]:
    """Resolve which gated tool families this project exposes to agents.

    Default is off for all of them, so a plain project pays no schema
    tokens for surface it never calls (US-PM-15).  Opting in is one line in
    ``.project/config.yaml``::

        tools:
          web: true

    No family takes any inference: ``maintenance`` (the break-glass
    cluster) and ``web`` are off until someone writes ``true``.
    ``config=None`` (no project found) means everything stays hidden.
    """
    if config is None:
        return {family: False for family in GATED_TOOL_FAMILIES}
    flags = config.tools
    return {
        "maintenance": bool(flags.maintenance),
        "web": bool(flags.web),
    }


def save_config(config: ProjectConfig, root: Optional[Path] = None) -> None:
    """Save config back to disk, dropping the cached copy for that root."""
    if root is None:
        root = find_project_root()
    root = Path(root).resolve()
    pdir = project_dir(root)
    config_path = pdir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False)
    # The bytes on disk just changed; drop the entry rather than trusting the
    # mtime/size stamp to notice (a same-size rewrite inside one filesystem
    # timestamp tick would not).
    clear_config_cache(root)
