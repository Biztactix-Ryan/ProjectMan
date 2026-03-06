"""Hub registry — manage subproject registration via git submodules."""

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from ..config import load_config, save_config


REF_LOG_MAX_ENTRIES = 500


def log_ref_update(
    project: str,
    old_ref: str,
    new_ref: str,
    source: str,
    root: Path,
    *,
    author: str = "",
    commit: str = "",
) -> None:
    """Append a ref update entry to .project/ref-log.yaml.

    Keeps the log append-only, capped at the last 500 entries.
    Older entries are rotated to ref-log.archive.yaml.

    Args:
        project: Name of the subproject whose ref changed.
        old_ref: Previous submodule commit SHA.
        new_ref: New submodule commit SHA.
        source: How the update happened (e.g. ``coordinated_push``,
            ``changeset``, ``manual``, ``sync``).
        root: Hub root directory.
        author: Who triggered the update (optional).
        commit: Hub commit SHA that recorded the change (optional).
    """
    log_path = root / ".project" / "ref-log.yaml"
    archive_path = root / ".project" / "ref-log.archive.yaml"

    # Load existing entries
    entries: list[dict] = []
    if log_path.exists():
        raw = yaml.safe_load(log_path.read_text())
        if isinstance(raw, list):
            entries = raw

    # Build new entry
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "old_ref": old_ref,
        "new_ref": new_ref,
        "source": source,
    }
    if author:
        entry["author"] = author
    if commit:
        entry["commit"] = commit

    entries.append(entry)

    # Rotate if over the cap
    if len(entries) > REF_LOG_MAX_ENTRIES:
        overflow = entries[:-REF_LOG_MAX_ENTRIES]
        entries = entries[-REF_LOG_MAX_ENTRIES:]

        # Append overflow to archive
        archived: list[dict] = []
        if archive_path.exists():
            raw = yaml.safe_load(archive_path.read_text())
            if isinstance(raw, list):
                archived = raw
        archived.extend(overflow)
        archive_path.write_text(yaml.safe_dump(archived, default_flow_style=False))

    log_path.write_text(yaml.safe_dump(entries, default_flow_style=False))


def _get_submodule_ref(project_name: str, root: Path) -> str:
    """Return the current commit SHA for a submodule, or '' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root / "projects" / project_name),
            capture_output=True,
            text=True,
            check=True,
        )
        return str(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def _get_hub_head(root: Path) -> str:
    """Return the current hub repo HEAD SHA, or '' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
        return str(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def _parse_github_repo(url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL, or return '' for non-GitHub URLs.

    Handles:
      https://github.com/owner/repo.git  → owner/repo
      https://github.com/owner/repo      → owner/repo
      git@github.com:owner/repo.git      → owner/repo
    """
    # HTTPS style
    m = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1)
    # SSH style
    m = re.match(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    return ""


def add_project(name: str, git_url: str, branch: Optional[str] = None, root: Optional[Path] = None) -> str:
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
        cmd = ["git", "submodule", "add"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [git_url, f"projects/{name}"]
        subprocess.run(
            cmd,
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        return f"error adding submodule: {e.stderr}"
    except FileNotFoundError:
        return "error: git is not installed or not on PATH"

    # Initialize PM data in hub's .project/projects/{name}/
    repo = _parse_github_repo(git_url)
    deploy_branch = branch or "main"
    pm_dir = root / ".project" / "projects" / name
    if not (pm_dir / "config.yaml").exists():
        _init_subproject(pm_dir, name, repo=repo, deploy_branch=deploy_branch)

    # Register in config
    if name not in config.projects:
        config.projects.append(name)
        save_config(config, root)

    msg = f"added project '{name}' from {git_url}"
    if branch:
        msg += f" (branch: {branch})"
    msg += f"\n\nRun /pm-init {name} to set up project documentation."
    return msg


def _init_subproject(target: Path, name: str, repo: str = "", deploy_branch: Optional[str] = None) -> None:
    """Initialize PM data directory for a subproject.

    ``target`` is the project dir itself (e.g. hub_root/.project/projects/{name}/).
    Stories, tasks, epics, config.yaml, and docs are created directly inside it.
    """
    import yaml
    from jinja2 import Environment, FileSystemLoader

    # Derive a prefix from the project name (e.g. "my-api" -> "API", "webapp" -> "WEB")
    clean = name.replace("-", "").replace("_", "")
    prefix = clean[:3].upper() or "PRJ"

    target.mkdir(parents=True, exist_ok=True)
    (target / "stories").mkdir(exist_ok=True)
    (target / "tasks").mkdir(exist_ok=True)
    (target / "epics").mkdir(exist_ok=True)

    # Try to render from templates, fall back to inline
    try:
        import importlib.resources
        tdir = str(importlib.resources.files("projectman") / "templates")
        env = Environment(loader=FileSystemLoader(tdir), keep_trailing_newline=True)
        ctx = dict(name=name, prefix=prefix, description="", repo=repo, hub=False,
                   deploy_branch=deploy_branch)

        (target / "config.yaml").write_text(env.get_template("config.yaml.j2").render(**ctx))
        (target / "PROJECT.md").write_text(env.get_template("project.md.j2").render(**ctx))
        (target / "INFRASTRUCTURE.md").write_text(env.get_template("infrastructure.md.j2").render(**ctx))
        (target / "SECURITY.md").write_text(env.get_template("security.md.j2").render(**ctx))
    except Exception:
        # Minimal fallback if templates aren't available
        config_data = {
            "name": name,
            "prefix": prefix,
            "description": "",
            "repo": repo,
            "hub": False,
            "next_story_id": 1,
            "projects": [],
        }
        if deploy_branch:
            config_data["deploy_branch"] = deploy_branch
        (target / "config.yaml").write_text(yaml.dump(config_data, default_flow_style=False))
        (target / "PROJECT.md").write_text(f"# {name}\n\n## Architecture\n\n## Key Decisions\n")
        (target / "INFRASTRUCTURE.md").write_text(f"# {name} — Infrastructure\n\n## Environments\n")
        (target / "SECURITY.md").write_text(f"# {name} — Security\n\n## Authentication\n")

    # Write empty index
    empty_index = {
        "entries": [],
        "total_points": 0,
        "completed_points": 0,
        "story_count": 0,
        "task_count": 0,
        "epic_count": 0,
    }
    (target / "index.yaml").write_text(yaml.dump(empty_index, default_flow_style=False))


def repair(root: Optional[Path] = None) -> str:
    """Scan the hub, fix missing pieces, import existing data, rebuild indexes.

    1. Discover unregistered projects in projects/ directory
    2. Initialize PM data in .project/projects/{name}/ where missing
    3. Rebuild each subproject's index.yaml
    4. Rebuild hub embeddings from all subprojects
    5. Regenerate hub dashboards
    """
    from ..config import find_project_root
    from ..indexer import build_index, write_index
    from ..store import Store

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project — run 'projectman init --hub' first"

    projects_dir = root / "projects"
    if not projects_dir.exists():
        projects_dir.mkdir()
        return "created projects/ directory — no projects found yet"

    report_lines = ["# Hub Repair Report\n"]
    registered_before = set(config.projects)
    changed = False

    # 1. Discover unregistered projects (directories in projects/ not in config)
    discovered = []
    for entry in sorted(projects_dir.iterdir()):
        if entry.is_dir() and entry.name not in config.projects:
            config.projects.append(entry.name)
            discovered.append(entry.name)
            changed = True

    if discovered:
        report_lines.append(f"## Discovered {len(discovered)} unregistered project(s)\n")
        for name in discovered:
            report_lines.append(f"- **{name}** — registered in hub config")
        report_lines.append("")

    # 2. Initialize PM data where missing, rebuild indexes where present
    initialized = []
    rebuilt = []
    story_counts = {}

    for name in config.projects:
        project_path = projects_dir / name
        pm_dir = root / ".project" / "projects" / name

        if not project_path.exists():
            report_lines.append(f"- **{name}** — directory missing, skipped")
            continue

        # Migration: if old-style projects/{name}/.project/ exists but new-style doesn't, move data
        old_style = project_path / ".project"
        if old_style.exists() and not (pm_dir / "config.yaml").exists():
            import shutil
            pm_dir.mkdir(parents=True, exist_ok=True)
            for item in old_style.iterdir():
                dest = pm_dir / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            report_lines.append(f"- **{name}** — migrated PM data from submodule to hub")

        if not (pm_dir / "config.yaml").exists():
            _init_subproject(pm_dir, name)
            initialized.append(name)
        else:
            # Project PM data exists — quarantine bad files, rebuild index
            try:
                import frontmatter as fm
                from ..models import StoryFrontmatter, TaskFrontmatter
                import shutil

                store = Store(root, project_dir=pm_dir)
                malformed_dir = store.project_dir / "malformed"
                quarantined = []

                # Check stories for bad frontmatter
                for path in sorted(store.stories_dir.glob("*.md")):
                    try:
                        post = fm.load(str(path))
                        StoryFrontmatter(**post.metadata)
                    except Exception as e:
                        malformed_dir.mkdir(exist_ok=True)
                        dest = malformed_dir / path.name
                        shutil.move(str(path), str(dest))
                        quarantined.append((path.name, str(e).split("\n")[0]))

                # Check tasks for bad frontmatter
                for path in sorted(store.tasks_dir.glob("*.md")):
                    try:
                        post = fm.load(str(path))
                        TaskFrontmatter(**post.metadata)
                    except Exception as e:
                        malformed_dir.mkdir(exist_ok=True)
                        dest = malformed_dir / path.name
                        shutil.move(str(path), str(dest))
                        quarantined.append((path.name, str(e).split("\n")[0]))

                if quarantined:
                    report_lines.append(f"### {name} — {len(quarantined)} malformed file(s) quarantined\n")
                    for fname, err in quarantined:
                        report_lines.append(f"- `{fname}` → `.project/projects/{name}/malformed/{fname}`: {err}")
                    report_lines.append("")

                stories = store.list_stories()
                tasks = store.list_tasks()
                write_index(store)
                rebuilt.append(name)
                story_counts[name] = {
                    "stories": len(stories),
                    "tasks": len(tasks),
                }
            except Exception as e:
                report_lines.append(f"- **{name}** — error rebuilding index: {e}")

    if initialized:
        report_lines.append(f"## Initialized {len(initialized)} project(s)\n")
        for name in initialized:
            report_lines.append(f"- **{name}** — created .project/ structure")
        report_lines.append("")
        report_lines.append("**Next step:** Run `/pm-init <project-name>` for each to set up documentation.\n")

    if rebuilt:
        report_lines.append(f"## Rebuilt indexes for {len(rebuilt)} project(s)\n")
        for name in rebuilt:
            counts = story_counts.get(name, {})
            s = counts.get("stories", 0)
            t = counts.get("tasks", 0)
            report_lines.append(f"- **{name}** — {s} stories, {t} tasks")
        report_lines.append("")

    # 3. Create missing hub docs (VISION.md, ARCHITECTURE.md, DECISIONS.md)
    hub_proj_dir = root / ".project"
    (hub_proj_dir / "epics").mkdir(exist_ok=True)
    hub_docs_created = []
    try:
        import importlib.resources
        from jinja2 import Environment, FileSystemLoader
        tdir = str(importlib.resources.files("projectman") / "templates")
        env = Environment(loader=FileSystemLoader(tdir), keep_trailing_newline=True)
        ctx = dict(name=config.name, prefix=config.prefix, description=config.description, hub=True)

        for doc_name, template_name in [
            ("VISION.md", "vision.md.j2"),
            ("ARCHITECTURE.md", "architecture_hub.md.j2"),
            ("DECISIONS.md", "decisions.md.j2"),
        ]:
            doc_path = hub_proj_dir / doc_name
            if not doc_path.exists():
                doc_path.write_text(env.get_template(template_name).render(**ctx))
                hub_docs_created.append(doc_name)
    except Exception:
        pass

    if hub_docs_created:
        report_lines.append(f"## Created {len(hub_docs_created)} missing hub doc(s)\n")
        for doc_name in hub_docs_created:
            report_lines.append(f"- **{doc_name}**")
        report_lines.append("")

    # 4. Rebuild hub embeddings from all subprojects
    embedded_count = 0
    try:
        from ..embeddings import EmbeddingStore

        emb_store = EmbeddingStore(hub_proj_dir)

        for name in config.projects:
            pm_dir = root / ".project" / "projects" / name
            if not (pm_dir / "config.yaml").exists():
                continue

            try:
                store = Store(root, project_dir=pm_dir)

                for story in store.list_stories():
                    _, body = store.get_story(story.id)
                    # Namespace IDs so they're unique across projects
                    hub_id = f"{name}/{story.id}"
                    emb_store.index_item(hub_id, f"[{name}] {story.title}", "story", body)
                    embedded_count += 1

                for task in store.list_tasks():
                    _, body = store.get_task(task.id)
                    hub_id = f"{name}/{task.id}"
                    emb_store.index_item(hub_id, f"[{name}] {task.title}", "task", body)
                    embedded_count += 1
            except Exception as e:
                report_lines.append(f"- **{name}** — embedding error: {e}")

        if embedded_count > 0:
            report_lines.append(f"## Rebuilt hub embeddings\n")
            report_lines.append(f"- Indexed {embedded_count} items across all projects")
            report_lines.append("")
    except ImportError:
        report_lines.append("## Embeddings skipped (sentence-transformers not installed)\n")

    # 5. Regenerate hub dashboards
    try:
        from .dashboards import generate_dashboards
        generate_dashboards(root)
        report_lines.append("## Regenerated hub dashboards\n")
        report_lines.append("- Updated status.md and burndown.md")
        report_lines.append("")
    except Exception as e:
        report_lines.append(f"## Dashboard generation failed: {e}\n")

    # 6. Save config if changed
    if changed:
        save_config(config, root)

    # Summary
    total_stories = sum(c.get("stories", 0) for c in story_counts.values())
    total_tasks = sum(c.get("tasks", 0) for c in story_counts.values())
    report_lines.append("## Summary\n")
    report_lines.append(f"- **Projects registered:** {len(config.projects)}")
    report_lines.append(f"- **Newly discovered:** {len(discovered)}")
    report_lines.append(f"- **Newly initialized:** {len(initialized)}")
    report_lines.append(f"- **Indexes rebuilt:** {len(rebuilt)}")
    report_lines.append(f"- **Total stories found:** {total_stories}")
    report_lines.append(f"- **Total tasks found:** {total_tasks}")
    report_lines.append(f"- **Items embedded:** {embedded_count}")

    report = "\n".join(report_lines)

    # Write repair report to hub
    (root / ".project" / "REPAIR.md").write_text(report + "\n")

    return report


def set_branch(name: str, branch: str, root: Optional[Path] = None) -> str:
    """Change the branch a submodule tracks and update it."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"

    if name not in config.projects:
        return f"error: project '{name}' not registered in hub"

    target = root / "projects" / name
    if not target.exists():
        return f"error: project '{name}' directory not found"

    try:
        # Update .gitmodules to track the new branch
        subprocess.run(
            ["git", "config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch", branch],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
        # Fetch and checkout the new branch in the submodule
        subprocess.run(
            ["git", "submodule", "update", "--remote", f"projects/{name}"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        return f"error switching branch: {e.stderr}"
    except FileNotFoundError:
        return "error: git is not installed or not on PATH"

    return f"project '{name}' now tracking branch '{branch}'"


def set_deploy_branch(name: str, branch: str, root: Optional[Path] = None) -> str:
    """Change the deploy branch for a subproject in its PM config.

    The deploy branch is the protected target for PRs — distinct from
    ``set_branch()`` which changes the .gitmodules tracking branch.
    """
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"

    if name not in config.projects:
        return f"error: project '{name}' not registered in hub"

    pm_dir = root / ".project" / "projects" / name
    config_path = pm_dir / "config.yaml"
    if not config_path.exists():
        return f"error: project '{name}' PM config not found"

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    data["deploy_branch"] = branch

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)

    return f"project '{name}' deploy branch set to '{branch}'"


def _get_deploy_branch(name: str, root: Path) -> str:
    """Return the deploy branch for a subproject from its PM config.

    Falls back to the .gitmodules tracking branch, then ``"main"``.
    """
    pm_config = root / ".project" / "projects" / name / "config.yaml"
    if pm_config.exists():
        data = yaml.safe_load(pm_config.read_text()) or {}
        if data.get("deploy_branch"):
            return str(data["deploy_branch"])
    # Fallback to tracking branch from .gitmodules
    tracking = _get_tracking_branch(name, root)
    return tracking or "main"


def validate_not_on_deploy_branch(
    project_name: str,
    root: Optional[Path] = None,
) -> str:
    """Check that a subproject is NOT on the deploy branch with uncommitted changes.

    If the subproject's HEAD is on the deploy branch and there are staged
    changes or modified tracked files, the developer should be on a feature
    branch instead.  Untracked files alone do not trigger this check.

    Returns an error string describing the problem, or an empty string
    when everything is fine.

    This check is intentionally skipped by ``sync()`` which legitimately
    pulls into the deploy branch.
    """
    from ..config import find_project_root

    root = root or find_project_root()

    deploy = _get_deploy_branch(project_name, root)
    current = _get_current_branch(project_name, root)

    if current == deploy and _has_tracked_changes(project_name, root):
        return (
            f"project '{project_name}' has uncommitted changes on the deploy "
            f"branch '{deploy}' — create a feature branch before committing"
        )

    return ""


def _slugify(text: str) -> str:
    """Convert text to a git-branch-safe slug."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def create_feature_branch(
    project_name: str,
    task_id: str,
    description: str,
    root: Optional[Path] = None,
) -> str:
    """Create a feature branch in a subproject linked to a task.

    Branch naming convention: ``pm/{task_id}/{slugified-description}``.

    Validates that the subproject exists, the working tree is clean,
    and the current branch is the deploy branch before creating.

    Returns the branch name on success, or an error string prefixed
    with ``"error:"``.
    """
    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"
    if project_name not in config.projects:
        return f"error: project '{project_name}' not registered in hub"

    target = root / "projects" / project_name
    if not target.exists():
        return f"error: project '{project_name}' directory not found"

    # Refuse if working tree is dirty
    if _is_dirty(project_name, root):
        return (
            f"error: project '{project_name}' has uncommitted changes — "
            "commit or stash before creating a feature branch"
        )

    # Must be on the deploy branch
    deploy = _get_deploy_branch(project_name, root)
    current = _get_current_branch(project_name, root)
    if current != deploy:
        return (
            f"error: project '{project_name}' is on branch '{current}', "
            f"not the deploy branch '{deploy}' — "
            "switch to the deploy branch before creating a feature branch"
        )

    slug = _slugify(description)
    if not slug:
        return "error: description produces an empty slug"
    branch_name = f"pm/{task_id}/{slug}"

    try:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        return f"error: failed to create branch '{branch_name}': {exc.stderr.strip()}"

    return branch_name


def list_feature_branches(
    project_name: str,
    root: Optional[Path] = None,
) -> list[str]:
    """List all ``pm/*`` feature branches in a subproject.

    Returns a sorted list of branch names, or an empty list on error.
    """
    from ..config import find_project_root

    root = root or find_project_root()
    target = root / "projects" / project_name
    if not target.exists():
        return []

    try:
        result = subprocess.run(
            ["git", "branch", "--list", "pm/*"],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []

    branches = []
    for line in result.stdout.splitlines():
        # git branch output has "  branch" or "* branch" prefix
        branch = line.lstrip("* ").strip()
        if branch:
            branches.append(branch)
    return sorted(branches)


def create_pr(
    project_name: str,
    title: str,
    body: str,
    root: Optional[Path] = None,
    *,
    draft: bool = False,
) -> dict:
    """Create a pull request targeting the deploy branch in a subproject.

    The current branch must be a ``pm/*`` feature branch — direct pushes
    to the deploy branch are blocked.  The feature branch is pushed to
    the remote before the PR is created.

    Args:
        project_name: Registered subproject name.
        title: PR title.
        body: PR body / description.
        root: Hub root directory.  Auto-detected when ``None``.
        draft: If ``True``, create a draft PR.

    Returns:
        A dict with keys:

        - ``url``: PR URL on success.
        - ``number``: PR number on success.
        - ``error``: Error message on failure (only present on failure).
    """
    import json as _json

    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {"error": "not a hub project"}
    if project_name not in config.projects:
        return {"error": f"project '{project_name}' not registered in hub"}

    target = root / "projects" / project_name
    if not target.exists():
        return {"error": f"project '{project_name}' directory not found"}

    # Must be on a pm/* feature branch
    current = _get_current_branch(project_name, root)
    if not current or current == "HEAD":
        return {"error": "detached HEAD — checkout a feature branch first"}
    if not current.startswith("pm/"):
        return {
            "error": (
                f"current branch '{current}' is not a pm/* feature branch — "
                "create a feature branch first"
            ),
        }

    deploy = _get_deploy_branch(project_name, root)

    # Push feature branch to remote
    try:
        push_result = subprocess.run(
            ["git", "push", "-u", "origin", current],
            cwd=str(target),
            capture_output=True,
            text=True,
        )
        if push_result.returncode != 0:
            stderr = (push_result.stderr or "").strip()
            return {"error": f"failed to push branch '{current}': {stderr}"}
    except FileNotFoundError:
        return {"error": "git is not installed or not on PATH"}
    except OSError as e:
        return {"error": f"push failed: {e}"}

    # Create PR via gh CLI
    cmd = [
        "gh", "pr", "create",
        "--base", deploy,
        "--head", current,
        "--title", title,
        "--body", body,
    ]
    if draft:
        cmd.append("--draft")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(target),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "gh auth" in stderr or "not logged" in stderr.lower():
                return {"error": "gh CLI not authenticated — run 'gh auth login'"}
            return {"error": f"gh pr create failed: {stderr}"}
    except FileNotFoundError:
        return {"error": "gh CLI is not installed — install from https://cli.github.com"}
    except OSError as e:
        return {"error": f"gh pr create failed: {e}"}

    pr_url = result.stdout.strip()

    # Extract PR number from the URL (last path segment)
    pr_number = 0
    if pr_url:
        try:
            pr_number = int(pr_url.rstrip("/").rsplit("/", 1)[-1])
        except (ValueError, IndexError):
            pass

    return {"url": pr_url, "number": pr_number}


def get_pr_status(
    project_name: str,
    root: Optional[Path] = None,
) -> dict:
    """Check open PRs targeting the deploy branch in a subproject.

    Uses ``gh pr list`` to find all open PRs whose base is the deploy
    branch.

    Args:
        project_name: Registered subproject name.
        root: Hub root directory.  Auto-detected when ``None``.

    Returns:
        A dict with keys:

        - ``deploy_branch``: The deploy branch name.
        - ``prs``: List of dicts with ``number``, ``title``, ``state``,
          and ``headRefName`` for each open PR.
        - ``error``: Error message on failure (only present on failure).
    """
    import json as _json

    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {"error": "not a hub project"}
    if project_name not in config.projects:
        return {"error": f"project '{project_name}' not registered in hub"}

    target = root / "projects" / project_name
    if not target.exists():
        return {"error": f"project '{project_name}' directory not found"}

    deploy = _get_deploy_branch(project_name, root)

    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--base", deploy,
                "--json", "number,title,state,headRefName",
            ],
            cwd=str(target),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "gh auth" in stderr or "not logged" in stderr.lower():
                return {"error": "gh CLI not authenticated — run 'gh auth login'"}
            return {"error": f"gh pr list failed: {stderr}"}
    except FileNotFoundError:
        return {"error": "gh CLI is not installed — install from https://cli.github.com"}
    except OSError as e:
        return {"error": f"gh pr list failed: {e}"}

    try:
        prs = _json.loads(result.stdout) if result.stdout.strip() else []
    except _json.JSONDecodeError:
        prs = []

    return {"deploy_branch": deploy, "prs": prs}


def _get_tracking_branch(name: str, root: Path) -> str:
    """Return the branch a submodule is configured to track in .gitmodules.

    Returns the branch string, or ``""`` if not set or on error.
    """
    try:
        result = subprocess.run(
            ["git", "config", "-f", ".gitmodules",
             f"submodule.projects/{name}.branch"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, OSError):
        pass
    return ""


def _get_current_branch(name: str, root: Path) -> str:
    """Return the current branch of a submodule, or ``""`` on error.

    Returns ``"HEAD"`` when the submodule is in detached HEAD state.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def _is_dirty(name: str, root: Path) -> bool:
    """Return ``True`` if the submodule has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def _has_staged_changes(name: str, root: Path) -> bool:
    """Return ``True`` if the submodule has changes staged in its index."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
        )
        # exit code 1 means there ARE staged changes
        return result.returncode != 0
    except (FileNotFoundError, OSError):
        return False


def _has_tracked_changes(name: str, root: Path) -> bool:
    """Return ``True`` if the submodule has staged or modified tracked files.

    Unlike :func:`_is_dirty`, this ignores untracked files (``??`` entries)
    which are not yet part of the commit.  This is the right check for
    deploy branch protection — only staged or modified tracked content
    indicates work that could be accidentally committed.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if line and not line.startswith("??"):
                return True
        return False
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def _remote_reachable(name: str, root: Path) -> bool:
    """Return ``True`` if ``origin`` is reachable for a submodule."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError, OSError,
            subprocess.TimeoutExpired):
        return False


def push_preflight(
    projects: Optional[list[str]] = None,
    root: Optional[Path] = None,
) -> dict:
    """Run all pre-push validations and return a combined readiness report.

    This is the gate — nothing gets pushed until preflight passes.

    Checks:
        1. ``validate_branches(strict=True)`` — every submodule on expected branch.
        2. ``validate_conventions()`` — branch naming, deploy protection (when available).
        3. ``validate_not_on_deploy_branch()`` — block dirty changes on deploy branch.
        4. For each dirty subproject: confirm it has staged changes (not just untracked).
        5. For each subproject to push: confirm remote is reachable.
        6. Confirm ``gh`` is available if PR workflow is enabled (when available).

    Args:
        projects: Optional list of project names to check.  When ``None``,
            checks all registered projects.
        root: Hub root directory.

    Returns:
        A dict with keys:

        - ``ready``: list of project names that can be pushed.
        - ``blocked``: list of dicts ``{"name": str, "reason": str}``
          for projects that cannot be pushed.
        - ``warnings``: list of human-readable non-blocking concerns.
        - ``can_proceed``: ``True`` only if no blockers exist.
    """
    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {
            "ready": [],
            "blocked": [{"name": "(hub)", "reason": "not a hub project"}],
            "warnings": [],
            "can_proceed": False,
        }

    # Determine which projects to check
    target_projects = projects if projects is not None else list(config.projects)

    ready: list[str] = []
    blocked: list[dict] = []
    warnings: list[str] = []

    # ── 1. Branch validation (strict mode for push gate) ──────
    branch_result = validate_branches(root=root, strict=True)

    # Build lookup sets for quick access
    misaligned_names = {r["name"] for r in branch_result["misaligned"]}
    detached_names = {r["name"] for r in branch_result["detached"]}
    missing_names = {r["name"] for r in branch_result["missing"]}

    # ── 2. Convention validation (when available) ─────────────
    try:
        from . import conventions
        if hasattr(conventions, "validate_conventions"):
            conv_result = conventions.validate_conventions(root=root)
            if conv_result.get("violations"):
                for v in conv_result["violations"]:
                    name = v.get("name", "unknown")
                    reason = v.get("reason", "convention violation")
                    if name in target_projects:
                        blocked.append({"name": name, "reason": reason})
    except (ImportError, AttributeError):
        pass  # US-PRJ-9 not implemented yet

    # Track which projects are already blocked by conventions
    convention_blocked = {b["name"] for b in blocked}

    # ── Per-project checks ────────────────────────────────────
    for name in target_projects:
        # Skip if already blocked by convention check
        if name in convention_blocked:
            continue

        project_path = root / "projects" / name

        # Missing directory — fatal
        if name in missing_names or not project_path.exists():
            blocked.append({"name": name, "reason": "project directory not found"})
            continue

        # Branch misalignment — fatal
        if name in misaligned_names:
            for r in branch_result["misaligned"]:
                if r["name"] == name:
                    blocked.append({
                        "name": name,
                        "reason": (
                            f"branch mismatch: on '{r['actual']}', "
                            f"expected '{r['expected']}'"
                        ),
                    })
                    break
            continue

        # Detached HEAD — fatal in strict mode
        if name in detached_names:
            for r in branch_result["detached"]:
                if r["name"] == name:
                    blocked.append({
                        "name": name,
                        "reason": (
                            f"detached HEAD (expected '{r['expected']}')"
                        ),
                    })
                    break
            continue

        # ── 3. Deploy branch protection ───────────────────────
        deploy_err = validate_not_on_deploy_branch(name, root)
        if deploy_err:
            blocked.append({"name": name, "reason": deploy_err})
            continue

        # ── 4. Dirty but no staged changes ────────────────────
        if _is_dirty(name, root) and not _has_staged_changes(name, root):
            warnings.append(
                f"{name}: dirty working tree but no staged changes — "
                f"nothing to commit"
            )

        # ── 5. Remote reachability ────────────────────────────
        if not _remote_reachable(name, root):
            blocked.append({
                "name": name,
                "reason": "remote 'origin' is not reachable",
            })
            continue

        ready.append(name)

    # ── 6. gh availability (when PR workflow is enabled) ──────
    # US-PRJ-7 not implemented yet — check config when available
    if getattr(config, "pr_workflow", False):
        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                warnings.append(
                    "gh CLI not available — PR workflow will not work"
                )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            warnings.append(
                "gh CLI not found — PR workflow requires GitHub CLI"
            )

    return {
        "ready": ready,
        "blocked": blocked,
        "warnings": warnings,
        "can_proceed": len(blocked) == 0,
    }


def validate_branches(root: Optional[Path] = None, *, strict: bool = False) -> dict:
    """Validate that each submodule's current branch matches .gitmodules tracking.

    Checks every registered project for:

    1. Configured branch from ``.gitmodules``
    2. Current HEAD branch
    3. Detached HEAD state
    4. Dirty working tree

    In **default mode** (``strict=False``), only ``misaligned`` and ``missing``
    entries cause ``ok=False``.  Detached HEAD and dirty working trees are
    reported as *informational* — common during development and not dangerous.

    In **strict mode** (``strict=True``), ``detached`` projects also cause
    ``ok=False``.  Use this before push operations where branch misalignment
    must block the push.

    Args:
        root: Hub root directory.
        strict: If ``True``, treat detached HEAD as a blocking error
            (for push gates).  Default ``False`` (informational only).

    Returns:
        A dict with keys:

        - ``aligned``: list of projects on the correct branch.
          Each entry: ``{"name", "branch", "dirty"}``.
        - ``misaligned``: list of projects on the wrong branch.
          Each entry: ``{"name", "expected", "actual", "dirty"}``.
        - ``detached``: list of projects in detached HEAD state.
          Each entry: ``{"name", "expected", "dirty"}``.
        - ``missing``: list of registered projects whose directory
          doesn't exist.  Each entry: ``{"name"}``.
        - ``ok``: ``True`` if no blocking issues found.  In default
          mode: no misaligned or missing.  In strict mode: also no
          detached.
        - ``strict``: Whether strict mode was used.
        - ``summary``: human-readable summary string.
    """
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {
            "aligned": [],
            "misaligned": [],
            "detached": [],
            "missing": [],
            "ok": False,
            "strict": strict,
            "summary": "Not a hub project.",
        }

    aligned: list[dict] = []
    misaligned: list[dict] = []
    detached: list[dict] = []
    missing: list[dict] = []

    for name in config.projects:
        target = root / "projects" / name
        if not target.exists():
            missing.append({"name": name})
            continue

        expected = _get_tracking_branch(name, root)
        if not expected:
            # No tracking branch configured — skip (defaults to remote HEAD)
            continue

        actual = _get_current_branch(name, root)
        if not actual:
            # Can't determine branch — treat as missing/broken
            missing.append({"name": name})
            continue

        dirty = _is_dirty(name, root)

        if actual == "HEAD":
            # Detached HEAD state
            detached.append({"name": name, "expected": expected, "dirty": dirty})
        elif actual == expected:
            aligned.append({"name": name, "branch": expected, "dirty": dirty})
        else:
            misaligned.append({
                "name": name,
                "expected": expected,
                "actual": actual,
                "dirty": dirty,
            })

    # In default mode, detached HEAD is informational (common during dev).
    # In strict mode (push gates), detached HEAD is blocking.
    if strict:
        ok = not misaligned and not detached and not missing
    else:
        ok = not misaligned and not missing

    # Build summary
    parts: list[str] = []
    total = len(aligned) + len(misaligned) + len(detached) + len(missing)
    if ok and not detached:
        if aligned:
            parts.append(f"All {len(aligned)} submodule(s) on correct branch.")
        else:
            parts.append("No submodules with tracking branches to validate.")
    else:
        if misaligned:
            parts.append(f"{len(misaligned)} misaligned")
        if detached:
            label = "detached (blocking)" if strict else "detached (info)"
            parts.append(f"{len(detached)} {label}")
        if missing:
            parts.append(f"{len(missing)} missing")
        if aligned:
            parts.append(f"{len(aligned)} ok")

    summary = ", ".join(parts) if parts else "No submodules to validate."

    return {
        "aligned": aligned,
        "misaligned": misaligned,
        "detached": detached,
        "missing": missing,
        "ok": ok,
        "strict": strict,
        "summary": summary,
    }


def format_branch_validation(result: dict) -> str:
    """Format a validate_branches result dict into a human-readable message.

    Args:
        result: Dict returned by :func:`validate_branches`.

    Returns:
        A formatted string summarising the validation outcome.
    """
    if result["ok"] and not result["detached"]:
        if not result["aligned"]:
            return "No submodules with tracking branches to validate."
        return f"All {len(result['aligned'])} submodule(s) on correct branch."

    lines: list[str] = []

    if result["ok"] and result["aligned"]:
        lines.append(f"{len(result['aligned'])} submodule(s) on correct branch.")

    if result["misaligned"]:
        lines.append("Branch mismatch detected:")
        for r in result["misaligned"]:
            line = f"  {r['name']}: expected '{r['expected']}', actual '{r['actual']}'"
            if r.get("dirty"):
                line += " (dirty)"
            lines.append(line)

    if result["detached"]:
        is_strict = result.get("strict", False)
        header = "Detached HEAD (blocking):" if is_strict else "Detached HEAD (informational):"
        lines.append(header)
        for r in result["detached"]:
            line = f"  {r['name']}: expected '{r['expected']}', HEAD is detached"
            if r.get("dirty"):
                line += " (dirty)"
            lines.append(line)

    if result["missing"]:
        lines.append("Missing directories:")
        for r in result["missing"]:
            lines.append(f"  {r['name']}: directory not found")

    return "\n".join(lines)


def sync(root: Optional[Path] = None) -> str:
    """Pull latest from all submodule remotes. Aborts cleanly on conflicts."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"

    projects_dir = root / "projects"
    if not projects_dir.exists():
        return "error: no projects/ directory"

    # Pre-sync branch validation (warn but continue — sync pulls from
    # the tracked branch regardless of local checkout)
    validation = validate_branches(root=root)
    branch_warnings: list[str] = []
    if validation["misaligned"]:
        for r in validation["misaligned"]:
            branch_warnings.append(
                f"  warning: {r['name']} on '{r['actual']}' "
                f"(expected '{r['expected']}') — sync will pull "
                f"from tracked branch anyway"
            )
    if validation["detached"]:
        for r in validation["detached"]:
            branch_warnings.append(
                f"  info: {r['name']} has detached HEAD "
                f"(expected '{r['expected']}')"
            )

    results = []
    ok = 0
    skipped = 0
    failed = 0

    for name in config.projects:
        target = projects_dir / name
        if not target.exists():
            results.append(f"  {name}: missing, skipped")
            skipped += 1
            continue

        # Check for dirty working tree
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target),
                capture_output=True,
                text=True,
                check=True,
            )
            if status.stdout.strip():
                results.append(f"  {name}: dirty working tree, skipped")
                skipped += 1
                continue
        except subprocess.CalledProcessError:
            results.append(f"  {name}: not a git repo, skipped")
            skipped += 1
            continue

        # Pull latest
        old_ref = _get_submodule_ref(name, root)
        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(target),
                check=True,
                capture_output=True,
                text=True,
            )
            new_ref = _get_submodule_ref(name, root)
            if old_ref != new_ref:
                log_ref_update(name, old_ref, new_ref, "sync", root)
            results.append(f"  {name}: updated")
            ok += 1
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.strip()
            if "Not possible to fast-forward" in stderr or "diverged" in stderr:
                results.append(f"  {name}: diverged, skipped (merge needed)")
            else:
                results.append(f"  {name}: error — {stderr}")
            failed += 1

    summary = f"sync complete: {ok} updated, {skipped} skipped, {failed} failed"
    parts = [summary]
    if branch_warnings:
        parts.append("\nbranch validation:")
        parts.extend(branch_warnings)
    parts.append("")
    parts.extend(results)
    return "\n".join(parts)


def list_projects(root: Optional[Path] = None) -> list[dict]:
    """List all registered projects with their status."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    results = []
    for name in config.projects:
        project_path = root / "projects" / name
        pm_dir = root / ".project" / "projects" / name
        has_pm_data = (pm_dir / "config.yaml").exists()
        results.append({
            "name": name,
            "path": str(project_path),
            "exists": project_path.exists(),
            "initialized": has_pm_data,
        })

    return results


def is_project_blocked_by_changeset(
    root: Path, project_name: str
) -> Optional[str]:
    """Check if a project is part of an open/partial changeset.

    Returns the changeset ID if the project is blocked, or ``None``
    if it's safe to update hub refs for this project.
    """
    from ..store import Store
    from ..models import ChangesetStatus

    store = Store(root)
    for cs in store.list_changesets():
        if cs.status in (ChangesetStatus.open, ChangesetStatus.partial):
            for entry in cs.entries:
                if entry.project == project_name:
                    return cs.id
    return None


def get_changeset_context(root: Optional[Path] = None) -> dict[str, dict]:
    """Get changeset context for each project that's part of an active changeset.

    Designed to augment ``git_status_all()`` output with changeset info per project.

    Returns a dict mapping project name to changeset context::

        {
            "api": {
                "changeset_id": "CS-PRJ-1",
                "changeset_name": "auth-v2",
                "changeset_status": "partial",
                "project_pr_status": "merged",
                "merged_count": 2,
                "total_count": 3,
                "waiting_on": ["worker"],
                "hub_ref_blocked": True,
                "summary": "auth-v2 (2/3 merged, waiting on worker)",
            },
        }

    Projects not in any active changeset are omitted from the result.
    """
    from ..config import find_project_root
    from ..models import ChangesetStatus
    from ..store import Store

    root = root or find_project_root()
    store = Store(root)

    context: dict[str, dict] = {}

    for cs in store.list_changesets():
        if cs.status not in (ChangesetStatus.open, ChangesetStatus.partial):
            continue

        merged = [e for e in cs.entries if e.status == "merged"]
        not_merged = [e for e in cs.entries if e.status != "merged"]
        merged_count = len(merged)
        total_count = len(cs.entries)

        for entry in cs.entries:
            waiting_on = [
                e.project for e in cs.entries
                if e.project != entry.project and e.status != "merged"
            ]

            if waiting_on:
                waiting_str = ", ".join(waiting_on)
                summary = f"{cs.title} ({merged_count}/{total_count} merged, waiting on {waiting_str})"
            elif merged_count == total_count:
                summary = f"{cs.title} ({total_count}/{total_count} merged)"
            else:
                summary = f"{cs.title} ({merged_count}/{total_count} merged)"

            # Flag if THIS project's PR is merged but others aren't
            this_merged = entry.status == "merged"
            others_pending = any(
                e.status != "merged"
                for e in cs.entries
                if e.project != entry.project
            )
            hub_ref_blocked = this_merged and others_pending

            # Customize summary for the blocked case
            if hub_ref_blocked:
                waiting_str = ", ".join(waiting_on)
                summary = f"{cs.title} ({merged_count}/{total_count} merged, THIS PR merged, waiting on {waiting_str})"

            context[entry.project] = {
                "changeset_id": cs.id,
                "changeset_name": cs.title,
                "changeset_status": cs.status.value,
                "project_pr_status": entry.status,
                "merged_count": merged_count,
                "total_count": total_count,
                "waiting_on": waiting_on,
                "hub_ref_blocked": hub_ref_blocked,
                "summary": summary,
            }

    return context


def update_hub_refs(
    changeset_id: str, root: Optional[Path] = None
) -> str:
    """Update hub submodule refs for all projects in a merged changeset.

    Validates that the changeset is fully merged before updating.  Each
    project's submodule ref is updated via ``git submodule update --remote``
    and staged, then all updates are committed in a single commit with
    message: ``hub: changeset {name} merged — update {project1}, {project2}, ...``

    Args:
        changeset_id: Changeset ID (e.g. ``CS-PRJ-1``).
        root: Hub root directory.

    Returns:
        A summary message describing what was updated, or an error string.
    """
    from ..config import find_project_root
    from ..models import ChangesetStatus
    from ..store import Store

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"

    store = Store(root)
    meta, _body = store.get_changeset(changeset_id)

    if meta.status != ChangesetStatus.merged:
        return (
            f"error: changeset {changeset_id} is not merged "
            f"(status: {meta.status.value})"
        )

    # Check that no project is blocked by *another* open changeset
    for entry in meta.entries:
        blocker = is_project_blocked_by_changeset(root, entry.project)
        if blocker and blocker != changeset_id:
            return (
                f"error: {entry.project} is blocked by open changeset "
                f"{blocker} — resolve it first"
            )

    projects_updated: list[str] = []
    ref_changes: list[tuple[str, str, str]] = []  # (project, old, new)
    for entry in meta.entries:
        project_path = root / "projects" / entry.project
        if not project_path.exists():
            continue

        old_ref = _get_submodule_ref(entry.project, root)

        try:
            subprocess.run(
                ["git", "submodule", "update", "--remote",
                 f"projects/{entry.project}"],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "add", f"projects/{entry.project}"],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )
            new_ref = _get_submodule_ref(entry.project, root)
            projects_updated.append(entry.project)
            ref_changes.append((entry.project, old_ref, new_ref))
        except subprocess.CalledProcessError as e:
            return f"error updating {entry.project}: {e.stderr}"

    if not projects_updated:
        return "no projects were updated"

    project_list = ", ".join(projects_updated)
    commit_msg = (
        f"hub: changeset {meta.title} merged \u2014 update {project_list}"
    )

    try:
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        return f"error committing: {e.stderr}"

    # Log ref updates after successful commit
    hub_sha = _get_hub_head(root)
    for proj, old, new in ref_changes:
        log_ref_update(proj, old, new, "changeset", root, commit=hub_sha)

    return f"updated hub refs for {project_list}"


def update_hub_refs_after_merge(
    projects: Optional[list[str]] = None,
    root: Optional[Path] = None,
) -> dict:
    """Update hub submodule refs only for projects whose PRs have been merged.

    Checks PR status via ``gh pr list`` for each project and only advances
    the submodule ref when all PRs targeting the deploy branch are merged
    (no open PRs remain).

    Args:
        projects: List of project names to check.  Defaults to all
            registered hub projects when ``None``.
        root: Hub root directory.  Auto-detected when ``None``.

    Returns:
        A dict with keys:

        - ``updated``: Projects whose submodule refs were advanced.
        - ``skipped``: Projects skipped because open PRs remain.
        - ``unchanged``: Projects with no ref change (no merged PRs or
          already up-to-date).
        - ``error``: A top-level error string, or ``None``.
    """
    import json as _json

    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {"updated": [], "skipped": [], "unchanged": [], "error": "not a hub project"}

    target_projects = projects if projects is not None else list(config.projects)

    # Validate project names
    for name in target_projects:
        if name not in config.projects:
            return {
                "updated": [], "skipped": [], "unchanged": [],
                "error": f"project '{name}' not registered in hub",
            }

    updated: list[dict] = []
    skipped: list[dict] = []
    unchanged: list[str] = []
    ref_changes: list[tuple[str, str, str]] = []  # (project, old, new)

    for name in target_projects:
        project_path = root / "projects" / name
        if not project_path.exists():
            unchanged.append(name)
            continue

        deploy = _get_deploy_branch(name, root)

        # Check for open PRs targeting the deploy branch
        open_prs: list[dict] = []
        try:
            result = subprocess.run(
                [
                    "gh", "pr", "list",
                    "--base", deploy,
                    "--state", "open",
                    "--json", "number,title,headRefName",
                ],
                cwd=str(project_path),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                open_prs = _json.loads(result.stdout)
        except (FileNotFoundError, OSError, _json.JSONDecodeError):
            pass

        if open_prs:
            skipped.append({
                "project": name,
                "reason": f"{len(open_prs)} open PR(s) pending",
                "open_prs": open_prs,
            })
            continue

        # Check for merged PRs targeting the deploy branch
        merged_prs: list[dict] = []
        try:
            result = subprocess.run(
                [
                    "gh", "pr", "list",
                    "--base", deploy,
                    "--state", "merged",
                    "--json", "number,title,mergedAt",
                ],
                cwd=str(project_path),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                merged_prs = _json.loads(result.stdout)
        except (FileNotFoundError, OSError, _json.JSONDecodeError):
            pass

        if not merged_prs:
            unchanged.append(name)
            continue

        # Merged PRs exist, no open PRs — safe to update submodule ref
        old_ref = _get_submodule_ref(name, root)

        try:
            subprocess.run(
                ["git", "submodule", "update", "--remote", f"projects/{name}"],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "add", f"projects/{name}"],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "updated": updated, "skipped": skipped, "unchanged": unchanged,
                "error": f"error updating {name}: {e.stderr}",
            }

        new_ref = _get_submodule_ref(name, root)

        if old_ref == new_ref:
            unchanged.append(name)
            continue

        updated.append({
            "project": name,
            "old_ref": old_ref,
            "new_ref": new_ref,
            "merged_prs": merged_prs,
        })
        ref_changes.append((name, old_ref, new_ref))

    # Commit if anything was updated
    if updated:
        project_list = ", ".join(u["project"] for u in updated)
        commit_msg = f"hub: update refs after merge — {project_list}"

        try:
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "updated": updated, "skipped": skipped, "unchanged": unchanged,
                "error": f"error committing: {e.stderr}",
            }

        # Log ref updates
        hub_sha = _get_hub_head(root)
        for proj, old, new in ref_changes:
            log_ref_update(proj, old, new, "pr_merge", root, commit=hub_sha)

    return {"updated": updated, "skipped": skipped, "unchanged": unchanged, "error": None}


MAX_PUSH_RETRIES = 3


def _analyze_remote_changes(root: Path) -> dict:
    """Analyze what changed between HEAD and origin/main.

    Returns a dict with:
        - ``submodule_only``: True if only ``projects/`` paths diverged.
        - ``project_files_changed``: True if ``.project/`` files diverged.
        - ``files``: list of all changed file paths.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "origin/main"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except subprocess.CalledProcessError:
        return {"submodule_only": False, "project_files_changed": False, "files": []}

    project_files = [f for f in files if f.startswith(".project/")]
    submodule_files = [f for f in files if f.startswith("projects/")]

    return {
        "submodule_only": bool(submodule_files) and not project_files,
        "project_files_changed": bool(project_files),
        "files": files,
    }


def _classify_rebase_conflict(root: Path) -> str:
    """Classify a rebase conflict by inspecting unmerged paths.

    Returns ``"project_files"`` if ``.project/`` files are conflicting,
    ``"submodule_ref"`` if only submodule paths conflict, or ``"unknown"``.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        conflicting = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except subprocess.CalledProcessError:
        conflicting = []

    if not conflicting:
        return "unknown"

    if any(f.startswith(".project/") for f in conflicting):
        return "project_files"
    if any(f.startswith("projects/") for f in conflicting):
        return "submodule_ref"
    return "unknown"


def check_ref_fast_forward(
    project_name: str,
    our_ref: str,
    their_ref: str,
    root: Path,
) -> dict:
    """Check if two submodule refs can be fast-forwarded.

    Uses ``git merge-base --is-ancestor`` in the subproject to determine
    the relationship between two refs.

    Args:
        project_name: Subproject directory name.
        our_ref: Our local submodule commit SHA.
        their_ref: The remote submodule commit SHA.
        root: Hub root directory.

    Returns:
        A dict with keys:
            - ``resolution``: ``"ours"``, ``"theirs"``, or ``"diverged"``
            - ``newer_ref``: the newer SHA (empty string if diverged)
            - ``message``: human-readable explanation
    """
    sub_path = root / "projects" / project_name

    # Check if their_ref is ancestor of our_ref → ours is newer
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", their_ref, our_ref],
            cwd=str(sub_path),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {
                "resolution": "ours",
                "newer_ref": our_ref,
                "message": (
                    f"project '{project_name}': ours ({our_ref[:7]}) is ahead "
                    f"of theirs ({their_ref[:7]}) — keeping ours"
                ),
            }
    except (FileNotFoundError, OSError):
        pass

    # Check if our_ref is ancestor of their_ref → theirs is newer
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", our_ref, their_ref],
            cwd=str(sub_path),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {
                "resolution": "theirs",
                "newer_ref": their_ref,
                "message": (
                    f"project '{project_name}': theirs ({their_ref[:7]}) is ahead "
                    f"of ours ({our_ref[:7]}) — taking theirs"
                ),
            }
    except (FileNotFoundError, OSError):
        pass

    # Neither is ancestor — diverged
    return {
        "resolution": "diverged",
        "newer_ref": "",
        "message": (
            f"Conflict: project '{project_name}' ref diverged.\n"
            f"  Local:  {our_ref}\n"
            f"  Remote: {their_ref}\n"
            f"  These branches diverged — resolve in the subproject first."
        ),
    }


def _get_conflicting_submodule_refs(root: Path) -> dict[str, tuple[str, str]]:
    """Extract conflicting submodule refs from the git index during a rebase.

    Parses ``git ls-files --unmerged`` to find submodule entries at stage 2
    (upstream/theirs in rebase context) and stage 3 (ours in rebase context).

    Returns:
        A dict mapping project name to ``(our_ref, their_ref)``.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--unmerged", "projects/"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return {}

    stages: dict[str, dict[int, str]] = {}
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        # Format: "<mode> <sha> <stage>\t<path>"
        tab_parts = line.split("\t", 1)
        if len(tab_parts) != 2:
            continue
        meta, path = tab_parts
        fields = meta.split()
        if len(fields) != 3:
            continue
        _mode, sha, stage_str = fields
        if path.startswith("projects/"):
            name = path.split("/")[1]
            stage = int(stage_str)
            if name not in stages:
                stages[name] = {}
            stages[name][stage] = sha

    # In rebase: stage 2 = upstream (their_ref), stage 3 = replayed (our_ref)
    conflicts = {}
    for name, stage_map in stages.items():
        our = stage_map.get(3, "")
        their = stage_map.get(2, "")
        if our and their:
            conflicts[name] = (our, their)

    return conflicts


def _resolve_submodule_ref_conflict(
    project_name: str, target_ref: str, root: Path,
) -> bool:
    """Resolve a submodule ref conflict by checking out the target ref.

    Checks out the desired commit in the subproject, then stages the
    resolution in the hub repo.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    sub_path = root / "projects" / project_name
    try:
        subprocess.run(
            ["git", "checkout", target_ref],
            cwd=str(sub_path),
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "add", f"projects/{project_name}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def hub_push_with_rebase(
    root: Optional[Path] = None, max_retries: int = MAX_PUSH_RETRIES
) -> dict:
    """Push hub commits to remote with intelligent auto-rebase on conflict.

    When ``git push origin main`` fails because the remote is ahead:

    1. ``git fetch origin main``
    2. Analyze what diverged (submodule refs vs ``.project/`` files)
    3. ``git rebase origin/main``
    4. If rebase succeeds → retry push
    5. If rebase has conflicts:

       a. Submodule ref conflict on same project → flag for fast-forward check
       b. ``.project/`` file conflict → abort rebase, flag for manual resolution

    6. Retry up to *max_retries* times

    Args:
        root: Hub root directory.
        max_retries: Maximum number of fetch-rebase-push cycles.

    Returns:
        ``{"pushed": bool, "retries": int, "rebased": bool, "error": str | None}``
    """
    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {"pushed": False, "retries": 0, "rebased": False, "error": "not a hub project"}

    rebased = False

    for retry in range(max_retries + 1):  # 0..max_retries
        # Try push
        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if push.returncode == 0:
            return {"pushed": True, "retries": retry, "rebased": rebased, "error": None}

        stderr = (push.stderr or "").strip()

        # Only handle push rejection (non-fast-forward)
        if not any(m in stderr for m in ("rejected", "failed to push", "non-fast-forward")):
            return {"pushed": False, "retries": retry, "rebased": False, "error": f"push failed: {stderr}"}

        # Don't rebase on the last attempt
        if retry == max_retries:
            break

        # Step 1: fetch
        fetch = subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if fetch.returncode != 0:
            return {
                "pushed": False, "retries": retry, "rebased": False,
                "error": f"fetch failed: {(fetch.stderr or '').strip()}",
            }

        # Step 2: analyze what diverged
        _analyze_remote_changes(root)

        # Snapshot submodule refs before rebase
        pre_refs = {
            name: _get_submodule_ref(name, root)
            for name in config.projects
            if (root / "projects" / name).exists()
        }

        # Step 3: rebase
        rebase = subprocess.run(
            ["git", "rebase", "origin/main"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )

        if rebase.returncode == 0:
            # Step 4: rebase succeeded — log ref changes, loop back to push
            rebased = True
            for name, old_ref in pre_refs.items():
                new_ref = _get_submodule_ref(name, root)
                if new_ref and old_ref != new_ref:
                    log_ref_update(name, old_ref, new_ref, "auto_rebase", root)
            continue

        # Step 5: rebase has conflicts — classify and attempt auto-resolution
        conflict_type = _classify_rebase_conflict(root)

        if conflict_type == "submodule_ref":
            # Try fast-forward auto-resolution before aborting
            conflicts = _get_conflicting_submodule_refs(root)
            if conflicts:
                resolutions = {}
                diverged_msgs = []

                for name, (our_ref, their_ref) in conflicts.items():
                    ff = check_ref_fast_forward(name, our_ref, their_ref, root)
                    if ff["resolution"] == "diverged":
                        diverged_msgs.append(ff["message"])
                    else:
                        resolutions[name] = ff

                if not diverged_msgs and resolutions:
                    # All fast-forwardable — resolve each conflict
                    all_ok = True
                    for name, ff in resolutions.items():
                        if not _resolve_submodule_ref_conflict(
                            name, ff["newer_ref"], root,
                        ):
                            all_ok = False
                            break

                    if all_ok:
                        cont = subprocess.run(
                            ["git", "rebase", "--continue"],
                            cwd=str(root),
                            capture_output=True,
                            text=True,
                            env={**os.environ, "GIT_EDITOR": "true"},
                        )
                        if cont.returncode == 0:
                            rebased = True
                            for name, old_ref in pre_refs.items():
                                new_ref = _get_submodule_ref(name, root)
                                if new_ref and old_ref != new_ref:
                                    log_ref_update(
                                        name, old_ref, new_ref,
                                        "auto_rebase", root,
                                    )
                            continue  # retry push

                # Auto-resolution failed or diverged — abort
                subprocess.run(
                    ["git", "rebase", "--abort"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                )
                if diverged_msgs:
                    return {
                        "pushed": False, "retries": retry + 1, "rebased": False,
                        "error": "\n".join(diverged_msgs),
                    }
                return {
                    "pushed": False, "retries": retry + 1, "rebased": False,
                    "error": "submodule ref conflict \u2014 auto-resolution failed",
                }

            # No conflicts parsed — abort with original message
            subprocess.run(
                ["git", "rebase", "--abort"],
                cwd=str(root),
                capture_output=True,
                text=True,
            )
            return {
                "pushed": False, "retries": retry + 1, "rebased": False,
                "error": "submodule ref conflict \u2014 check if fast-forwardable",
            }

        # Non-submodule conflicts — abort and report
        subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if conflict_type == "project_files":
            return {
                "pushed": False, "retries": retry + 1, "rebased": False,
                "error": "rebase conflict in .project/ files \u2014 manual resolution required",
            }
        return {
            "pushed": False, "retries": retry + 1, "rebased": False,
            "error": "rebase conflict \u2014 manual resolution required",
        }

    return {
        "pushed": False, "retries": max_retries, "rebased": rebased,
        "error": "push rejected after max retries",
    }


def push_hub(
    pushed_projects: Optional[list[dict]] = None,
    root: Optional[Path] = None,
    max_retries: int = MAX_PUSH_RETRIES,
) -> dict:
    """Push hub commits to remote, optionally staging submodule ref updates first.

    When *pushed_projects* is provided, stages each project's updated
    submodule ref (``git add projects/{name}``), generates a commit
    message, and commits before pushing.  When omitted, just pushes
    existing commits.

    Delegates to :func:`hub_push_with_rebase` for push-with-rebase
    conflict handling.

    Args:
        pushed_projects: Optional list of dicts with ``"name"`` and
            ``"sha"`` keys — one per subproject whose ref should be
            staged and committed before pushing.
        root: Hub root directory.
        max_retries: Maximum number of push attempts (including the first).

    Returns:
        A dict with keys:

        - ``committed``: Whether a new hub commit was created.
        - ``pushed``: Whether the push succeeded.
        - ``commit_sha``: Hub commit SHA after staging + commit,
          or ``None`` if no commit was made.
        - ``error``: Error message if something failed, else ``None``.
        - ``status``: ``"pushed"``, ``"rebased_and_pushed"``, or
          ``"failed"``.
        - ``attempts``: Number of push attempts made.
    """
    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {
            "committed": False,
            "pushed": False,
            "commit_sha": None,
            "error": "not a hub project",
            "status": "failed",
            "attempts": 0,
        }

    committed = False
    commit_sha: Optional[str] = None

    # ── Stage and commit submodule ref updates ──────────────
    if pushed_projects:
        try:
            for entry in pushed_projects:
                subprocess.run(
                    ["git", "add", f"projects/{entry['name']}"],
                    cwd=str(root),
                    check=True,
                    capture_output=True,
                    text=True,
                )
        except subprocess.CalledProcessError as e:
            return {
                "committed": False,
                "pushed": False,
                "commit_sha": None,
                "error": f"staging failed: {(e.stderr or '').strip()}",
                "status": "failed",
                "attempts": 0,
            }

        # Generate commit message:
        # hub: update api, web to a1b2c3d, d4e5f6g
        names = [e["name"] for e in pushed_projects]
        shas = [
            e["sha"][:7] if e.get("sha") else "unknown"
            for e in pushed_projects
        ]
        commit_msg = f"hub: update {', '.join(names)} to {', '.join(shas)}"

        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            committed = True
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            commit_sha = sha_result.stdout.strip()
        else:
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            # "nothing to commit" is OK — refs may not have changed
            if "nothing to commit" not in output:
                return {
                    "committed": False,
                    "pushed": False,
                    "commit_sha": None,
                    "error": f"commit failed: {stderr}",
                    "status": "failed",
                    "attempts": 0,
                }

    # ── Push with auto-rebase ─────────────────────────────
    # hub_push_with_rebase treats max_retries as *additional* retries after
    # the first attempt, while push_hub treats it as total attempts.
    rebase_result = hub_push_with_rebase(
        root=root, max_retries=max(0, max_retries - 1),
    )

    attempts = rebase_result["retries"] + 1

    if rebase_result["pushed"]:
        status = "pushed" if not rebase_result["rebased"] else "rebased_and_pushed"
        # If rebased, update commit_sha to final HEAD
        if rebase_result["rebased"] or commit_sha is None:
            final_sha = _get_hub_head(root)
            if final_sha:
                commit_sha = final_sha
        return {
            "committed": committed,
            "pushed": True,
            "commit_sha": commit_sha,
            "status": status,
            "attempts": attempts,
        }

    return {
        "committed": committed,
        "pushed": False,
        "commit_sha": commit_sha,
        "error": rebase_result["error"] or "push failed",
        "status": "failed",
        "attempts": attempts,
    }


def _has_unpushed_commits(name: str, root: Path) -> bool:
    """Check if a subproject has commits not yet pushed to origin."""
    sub_path = root / "projects" / name
    branch = _get_current_branch(name, root)
    if not branch or branch == "HEAD":
        return False
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"origin/{branch}..{branch}"],
            cwd=str(sub_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return True
        return int(result.stdout.strip()) > 0
    except (FileNotFoundError, OSError, ValueError):
        return False


def push_subprojects(
    projects: list[str],
    root: Path,
) -> dict:
    """Push feature branches for each specified subproject in order.

    For each project (order matters — push in the order given):
    1. Check if the project has unpushed commits (skip if up to date).
    2. ``git push -u origin {branch}`` in the subproject dir.
    3. Record result: success (branch + SHA) or failure (error).
    4. On failure: **stop** — remaining projects are skipped.

    Args:
        projects: Ordered list of project names to push.
        root: Hub root directory.

    Returns:
        A dict with keys:
        - ``pushed``: list of dicts ``{"name", "branch", "sha"}``
        - ``failed``: ``{"name", "error"}`` or ``None``
        - ``skipped``: list of project names after the failure
        - ``all_ok``: ``True`` if all pushes succeeded
    """
    pushed: list[dict] = []
    failed: Optional[dict] = None
    skipped: list[str] = []

    for i, name in enumerate(projects):
        sub_path = root / "projects" / name

        if not _has_unpushed_commits(name, root):
            continue

        branch = _get_current_branch(name, root)
        if not branch or branch == "HEAD":
            failed = {
                "name": name,
                "error": "detached HEAD \u2014 checkout a branch first",
            }
            skipped = list(projects[i + 1:])
            break

        try:
            result = subprocess.run(
                ["git", "push", "-u", "origin", branch],
                cwd=str(sub_path),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                failed = {
                    "name": name,
                    "error": f"push failed: {stderr}",
                }
                skipped = list(projects[i + 1:])
                break

            sha = _get_submodule_ref(name, root)
            pushed.append({"name": name, "branch": branch, "sha": sha})

        except FileNotFoundError:
            failed = {
                "name": name,
                "error": "git is not installed or not on PATH",
            }
            skipped = list(projects[i + 1:])
            break
        except OSError as e:
            failed = {"name": name, "error": str(e)}
            skipped = list(projects[i + 1:])
            break

    return {
        "pushed": pushed,
        "failed": failed,
        "skipped": skipped,
        "all_ok": failed is None,
    }


def _discover_dirty_projects(root: Path, config) -> list[str]:
    """Return names of registered projects that have unpushed commits."""
    dirty: list[str] = []
    for name in config.projects:
        project_path = root / "projects" / name
        if not project_path.exists():
            continue
        if _has_unpushed_commits(name, root):
            dirty.append(name)
    return dirty


def coordinated_push(
    projects: Optional[list[str]] = None,
    dry_run: bool = False,
    root: Optional[Path] = None,
    max_retries: int = MAX_PUSH_RETRIES,
) -> dict:
    """Orchestrate a coordinated push of subprojects followed by the hub.

    Full workflow:

    1. Discover dirty projects (or use explicit list if provided).
    2. Run :func:`push_preflight` — abort if ``can_proceed=False``.
    3. If *dry_run*: print what WOULD happen and exit.
    4. Run :func:`push_subprojects` — stop on first failure.
    5. If all subprojects pushed: run :func:`push_hub`.
    6. Print final report.

    Args:
        projects: Optional list of project names to push.  When ``None``,
            discovers all dirty (unpushed) projects automatically.
        dry_run: If ``True``, report what would happen without pushing.
        root: Hub root directory.
        max_retries: Maximum number of push attempts (including the first).

    Returns:
        A dict with keys:
            - ``pushed``: Whether the hub was pushed successfully.
            - ``hub_result``: Raw result from :func:`hub_push_with_rebase`.
            - ``report``: Human-readable push report string.
    """
    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {
            "pushed": False,
            "hub_result": None,
            "report": "error: not a hub project",
        }

    # ── Step 1: Discover dirty projects ─────────────────────────
    if projects is not None:
        target_projects = list(projects)
    else:
        target_projects = _discover_dirty_projects(root, config)

    # ── Step 2: Preflight ───────────────────────────────────────
    preflight = push_preflight(
        projects=target_projects if target_projects else None,
        root=root,
    )

    if not preflight["can_proceed"]:
        blocker_lines = []
        for b in preflight["blocked"]:
            blocker_lines.append(
                f"  {b['name']}  \u2717  ({b['reason']})"
            )
        return {
            "pushed": False,
            "hub_result": None,
            "report": (
                "Coordinated Push \u2014 Preflight FAILED\n\n"
                f"  Preflight: {len(preflight['ready'])} ready, "
                f"{len(preflight['blocked'])} blocked\n"
                "  Blockers:\n" + "\n".join(blocker_lines)
            ),
        }

    # ── Step 3: Dry run ─────────────────────────────────────────
    if dry_run:
        report_lines: list[str] = ["Coordinated Push — Dry Run\n"]
        report_lines.append(
            f"  Preflight: {len(preflight['ready'])} ready, "
            f"{len(preflight['blocked'])} blocked"
        )
        if preflight["warnings"]:
            for w in preflight["warnings"]:
                report_lines.append(f"  Warning: {w}")
        report_lines.append("  Subprojects:")
        for name in target_projects:
            branch = _get_current_branch(name, root)
            if _has_unpushed_commits(name, root):
                report_lines.append(
                    f"    {name}  {branch} \u2192 origin  (would push)"
                )
            else:
                report_lines.append(f"    {name}  (clean, would skip)")
        report_lines.append("  Hub:")
        report_lines.append("    main \u2192 origin  (would push)")
        return {
            "pushed": False,
            "hub_result": None,
            "report": "\n".join(report_lines),
        }

    report_lines: list[str] = []

    # ── Step 4: Push subprojects first ──────────────────────────
    sub_result = push_subprojects(target_projects, root)

    has_sub_content = (
        sub_result["pushed"]
        or sub_result["failed"]
        or sub_result["skipped"]
    )
    if has_sub_content:
        report_lines.append("Subprojects:")
        for entry in sub_result["pushed"]:
            sha_short = entry["sha"][:7] if entry["sha"] else "unknown"
            report_lines.append(
                f"  {entry['name']}  {entry['branch']} \u2192 origin  "
                f"{sha_short}  \u2713"
            )
        if sub_result["failed"]:
            fail = sub_result["failed"]
            report_lines.append(
                f"  {fail['name']}  \u2717  ({fail['error']})"
            )
        for name in sub_result["skipped"]:
            report_lines.append(f"  {name}  skipped")

    # ── Step 2: If subprojects failed, skip hub push ────────────
    if not sub_result["all_ok"]:
        report_lines.append("Hub:")
        report_lines.append("  skipped (subproject push failed)")
        return {
            "pushed": False,
            "hub_result": None,
            "sub_result": sub_result,
            "report": "\n".join(report_lines),
        }

    # ── Step 3: Push hub with auto-rebase ───────────────────────
    hub_result = hub_push_with_rebase(
        root=root, max_retries=max(0, max_retries - 1),
    )

    report_lines.append("Hub:")
    hub_sha = _get_hub_head(root) if hub_result["pushed"] else ""

    if hub_result["pushed"]:
        sha_short = hub_sha[:7] if hub_sha else "unknown"
        if hub_result["rebased"]:
            retries = hub_result["retries"]
            retry_label = "1 retry" if retries == 1 else f"{retries} retries"
            report_lines.append(
                f"  main \u2192 origin  {sha_short}  \u2713  "
                f"(rebased, {retry_label})"
            )
        else:
            report_lines.append(
                f"  main \u2192 origin  {sha_short}  \u2713"
            )
    else:
        error = hub_result.get("error") or "unknown error"
        retries = hub_result["retries"]

        if "diverged" in error:
            report_lines.append("  main \u2192 origin  \u2717  (diverged ref conflict)")
            report_lines.append(f"  {error}")
            report_lines.append(
                "  Suggestion: resolve the conflict in the "
                "subproject first, then retry"
            )
        elif "max retries" in error:
            report_lines.append(
                f"  main \u2192 origin  \u2717  "
                f"(failed after {retries} retries, "
                f"manual resolution needed)"
            )
        else:
            report_lines.append(f"  main \u2192 origin  \u2717  ({error})")

    return {
        "pushed": hub_result["pushed"],
        "hub_result": hub_result,
        "sub_result": sub_result,
        "report": "\n".join(report_lines),
    }


def _generate_hub_commit_message(changed_files: list[str]) -> str:
    """Generate a commit message from changed .project/ file paths.

    Parses story/task/epic IDs from filenames and produces messages like
    ``pm: update US-PRJ-5, US-PRJ-3-1`` or ``pm: update 3 stories, 2 tasks``.
    Falls back to count-based summaries when there are many changed items.
    """
    ids: list[str] = []
    config_changed = False
    other = 0

    for f in changed_files:
        name = Path(f).stem  # e.g. "US-PRJ-5" from ".project/stories/US-PRJ-5.md"
        if "/stories/" in f:
            ids.append(name)
        elif "/tasks/" in f:
            ids.append(name)
        elif "/epics/" in f:
            ids.append(name)
        elif Path(f).name in ("config.yaml", "index.yaml"):
            config_changed = True
        else:
            other += 1

    # If few enough IDs, list them explicitly
    if ids and len(ids) <= 4:
        return f"pm: update {', '.join(ids)}"

    # Otherwise, summarise by type counts
    stories = sum(1 for f in changed_files if "/stories/" in f)
    tasks = sum(1 for f in changed_files if "/tasks/" in f)
    epics = sum(1 for f in changed_files if "/epics/" in f)

    parts: list[str] = []
    if stories:
        parts.append(f"{stories} {'story' if stories == 1 else 'stories'}")
    if tasks:
        parts.append(f"{tasks} {'task' if tasks == 1 else 'tasks'}")
    if epics:
        parts.append(f"{epics} {'epic' if epics == 1 else 'epics'}")
    if config_changed:
        parts.append("config")
    if other:
        parts.append(f"{other} {'file' if other == 1 else 'files'}")

    if parts:
        return f"pm: update {', '.join(parts)}"
    return "pm: update project data"


def pm_commit(
    scope: str = "all",
    message: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict:
    """Commit .project/ changes filtered by scope.

    Scope options:

    - ``"hub"`` — commits only hub-level ``.project/`` files (stories,
      tasks, epics, config, dashboards) but **not** files under
      ``.project/projects/``.
    - ``"project:{name}"`` — commits only ``.project/projects/{name}/``
      files.
    - ``"all"`` — commits all ``.project/`` changes (hub + all
      subprojects).

    Args:
        scope: One of ``"hub"``, ``"project:{name}"``, or ``"all"``.
        message: Commit message.  Auto-generated from changed filenames
            when ``None``.
        root: Hub root directory.  Auto-detected when ``None``.

    Returns:
        A dict with ``commit_hash``, ``message``, and ``files_committed``,
        or ``{"nothing_to_commit": True}`` when there are no matching
        changes.

    Raises:
        FileNotFoundError: If ``.project/`` doesn't exist.
        ValueError: If *scope* is invalid.
        RuntimeError: If the git commit fails.
    """
    from ..config import find_project_root

    root = root or find_project_root()
    project_dir = root / ".project"

    if not project_dir.exists():
        raise FileNotFoundError(".project/ directory does not exist")

    # Validate scope
    if scope == "hub":
        pass
    elif scope == "all":
        pass
    elif scope.startswith("project:"):
        project_name = scope.split(":", 1)[1]
        sub_dir = project_dir / "projects" / project_name
        if not sub_dir.exists():
            raise ValueError(
                f"Project '{project_name}' not found in "
                f".project/projects/"
            )
    else:
        raise ValueError(
            f"Invalid scope '{scope}' — use 'hub', 'project:{{name}}', "
            f"or 'all'"
        )

    # 1. Find changed PM files (--untracked-files=all lists individual
    #    files instead of collapsing untracked directories; scoped to
    #    .project/ so the performance cost is negligible)
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", ".project/"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git status failed: {result.stderr.strip()}")

    # Parse porcelain output — each line is "XY path" or "XY path -> path"
    all_changed: list[str] = []
    for line in result.stdout.splitlines():
        if not line or len(line) < 4:
            continue
        # Status is first 2 chars, then a space, then the path
        path = line[3:].strip()
        # Handle renames: "R  old -> new"
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            all_changed.append(path)

    if not all_changed:
        return {"nothing_to_commit": True}

    # 2. Filter to scope
    if scope == "all":
        scoped_files = all_changed
    elif scope == "hub":
        # Hub-level = everything in .project/ EXCEPT .project/projects/
        scoped_files = [
            f for f in all_changed
            if not f.startswith(".project/projects/")
        ]
    else:
        # scope == "project:{name}"
        project_name = scope.split(":", 1)[1]
        prefix = f".project/projects/{project_name}/"
        scoped_files = [f for f in all_changed if f.startswith(prefix)]

    if not scoped_files:
        return {"nothing_to_commit": True}

    # 3. Stage only the scoped files
    subprocess.run(
        ["git", "add", "--"] + scoped_files,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )

    # Verify something was staged (handles edge cases)
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    staged = [f for f in diff_result.stdout.strip().splitlines() if f]
    if not staged:
        return {"nothing_to_commit": True}

    # 4. Auto-generate message if not provided
    if message is None:
        message = _generate_hub_commit_message(staged)

    # 5. Commit
    commit_result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if commit_result.returncode != 0:
        raise RuntimeError(
            f"git commit failed: {commit_result.stderr.strip()}"
        )

    # 6. Get commit SHA
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )

    return {
        "commit_hash": sha_result.stdout.strip(),
        "message": message,
        "files_committed": staged,
    }


def _push_subproject(name: str, root: Path) -> dict:
    """Push a single subproject on its current branch.

    Runs ``git push origin <branch>`` inside ``projects/{name}/``.

    Args:
        name: Subproject directory name.
        root: Hub root directory.

    Returns:
        A dict with ``pushed``, ``branch``, and optionally ``error``.
    """
    sub_path = root / "projects" / name

    # Get current branch
    branch = _get_current_branch(name, root)
    if not branch or branch == "HEAD":
        return {
            "pushed": False,
            "error": (
                f"project '{name}' is in detached HEAD state "
                f"— checkout a branch first"
            ),
        }

    try:
        result = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=str(sub_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            return {"pushed": False, "branch": branch, "error": f"push failed: {stderr}"}
        return {"pushed": True, "branch": branch}
    except FileNotFoundError:
        return {"pushed": False, "error": "git is not installed or not on PATH"}
    except OSError as e:
        return {"pushed": False, "error": str(e)}


def pm_push(
    scope: str = "hub",
    root: Optional[Path] = None,
) -> dict:
    """Push changes with scope-aware validation.

    Validates branches before pushing and routes to the appropriate
    push strategy based on scope.

    Scope options:

    - ``"hub"`` — pushes the hub repo on main via :func:`push_hub`.
    - ``"project:{name}"`` — pushes a specific subproject on its
      current branch.
    - ``"all"`` — delegates to :func:`coordinated_push`.

    Before pushing:

    1. Validate scope and project existence.
    2. Run :func:`validate_branches` in strict mode for the scoped
       projects.
    3. Abort with a clear message if validation fails.

    Args:
        scope: One of ``"hub"``, ``"project:{name}"``, or ``"all"``.
        root: Hub root directory.  Auto-detected when ``None``.

    Returns:
        A dict with keys:

        - ``pushed``: Whether the push succeeded.
        - ``scope``: The scope that was used.
        - ``error``: Error message (only present on failure).
        - Additional scope-specific keys (``branch``, ``report``, etc.).
    """
    from ..config import find_project_root

    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {"pushed": False, "scope": scope, "error": "not a hub project"}

    # ── Validate scope ──────────────────────────────────────────
    project_name: Optional[str] = None
    if scope == "hub":
        pass
    elif scope == "all":
        pass
    elif scope.startswith("project:"):
        project_name = scope.split(":", 1)[1]
        if project_name not in config.projects:
            return {
                "pushed": False,
                "scope": scope,
                "error": f"project '{project_name}' not registered in hub",
            }
        target = root / "projects" / project_name
        if not target.exists():
            return {
                "pushed": False,
                "scope": scope,
                "error": f"project '{project_name}' directory not found",
            }
    else:
        return {
            "pushed": False,
            "scope": scope,
            "error": (
                f"invalid scope '{scope}' — "
                f"use 'hub', 'project:{{name}}', or 'all'"
            ),
        }

    # ── Pre-push validation: validate_branches (strict) ─────────
    if scope == "hub":
        # Hub itself is always on main; no submodule branch check needed.
        pass
    elif scope.startswith("project:"):
        assert project_name is not None
        validation = validate_branches(root=root, strict=True)
        # Check this specific project
        for entry in validation["misaligned"]:
            if entry["name"] == project_name:
                return {
                    "pushed": False,
                    "scope": scope,
                    "error": (
                        f"branch validation failed: {project_name} on "
                        f"'{entry['actual']}' (expected '{entry['expected']}')"
                    ),
                }
        for entry in validation["detached"]:
            if entry["name"] == project_name:
                return {
                    "pushed": False,
                    "scope": scope,
                    "error": (
                        f"branch validation failed: {project_name} has "
                        f"detached HEAD (expected '{entry['expected']}')"
                    ),
                }
        for entry in validation["missing"]:
            if entry["name"] == project_name:
                return {
                    "pushed": False,
                    "scope": scope,
                    "error": (
                        f"branch validation failed: {project_name} "
                        f"directory missing"
                    ),
                }
    else:
        # scope == "all"
        validation = validate_branches(root=root, strict=True)
        if not validation["ok"]:
            return {
                "pushed": False,
                "scope": scope,
                "error": (
                    f"branch validation failed: {validation['summary']}"
                ),
                "validation": validation,
            }

    # ── Execute push ────────────────────────────────────────────
    if scope == "all":
        result = coordinated_push(root=root)
        result["scope"] = scope
        return result

    if scope == "hub":
        hub_result = push_hub(root=root)
        pushed = hub_result["status"] != "failed"
        out: dict = {
            "pushed": pushed,
            "scope": scope,
            "status": hub_result["status"],
            "attempts": hub_result["attempts"],
        }
        if not pushed:
            out["error"] = hub_result.get("error", "push failed")
        return out

    # scope == "project:{name}"
    assert project_name is not None
    result = _push_subproject(project_name, root)
    result["scope"] = scope
    return result


# ─── git status dashboard ──────────────────────────────────────────


def _get_ahead_behind(name: str, root: Path) -> tuple[int, int]:
    """Return (ahead, behind) counts for a submodule vs its remote tracking branch.

    Returns ``(0, 0)`` on any error (no remote, detached HEAD, etc.).
    """
    branch = _get_current_branch(name, root)
    if not branch or branch == "HEAD":
        return (0, 0)
    try:
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count",
             f"origin/{branch}...{branch}"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return (0, 0)
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            return (int(parts[1]), int(parts[0]))
        return (0, 0)
    except (FileNotFoundError, OSError, ValueError):
        return (0, 0)


def _get_dirty_count(name: str, root: Path) -> int:
    """Return the number of modified/untracked files in a submodule."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        return len(lines)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return 0


def _get_last_commit(name: str, root: Path) -> dict:
    """Return last commit info for a submodule.

    Returns a dict with ``sha``, ``date``, ``author``, ``message`` keys.
    All values are empty strings on error.
    """
    empty = {"sha": "", "date": "", "author": "", "message": ""}
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H|%ai|%an|%s"],
            cwd=str(root / "projects" / name),
            capture_output=True,
            text=True,
            check=True,
        )
        parts = result.stdout.strip().split("|", 3)
        if len(parts) == 4:
            return {
                "sha": parts[0],
                "date": parts[1],
                "author": parts[2],
                "message": parts[3],
            }
        return empty
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return empty


def _get_open_prs(name: str, root: Path, deploy_branch: str) -> list[dict]:
    """Return open PRs targeting *deploy_branch* for a subproject.

    Uses ``gh pr list`` to query GitHub.  Returns a (possibly empty) list of
    dicts with ``number``, ``title``, ``branch``, ``draft``, and ``updated``
    keys.

    Fails gracefully — returns ``[]`` when ``gh`` is not installed, not
    authenticated, or the remote is not a GitHub repo.
    """
    import json as _json

    target = root / "projects" / name
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--base", deploy_branch,
                "--state", "open",
                "--json", "number,title,headRefName,isDraft,updatedAt",
                "--limit", "10",
            ],
            cwd=str(target),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, OSError):
        return []

    try:
        raw = _json.loads(result.stdout) if result.stdout.strip() else []
    except _json.JSONDecodeError:
        return []

    return [
        {
            "number": pr.get("number", 0),
            "title": pr.get("title", ""),
            "branch": pr.get("headRefName", ""),
            "draft": pr.get("isDraft", False),
            "updated": pr.get("updatedAt", ""),
        }
        for pr in raw
    ]


def _collect_project_status(name: str, root: Path) -> dict:
    """Collect all git status fields for a single subproject.

    Runs all git commands for one project and returns its full status dict.
    Designed to be called in parallel via ThreadPoolExecutor.
    """
    target = root / "projects" / name
    if not target.exists():
        return {
            "name": name,
            "branch": "",
            "tracking_branch": "",
            "deploy_branch": "main",
            "aligned": False,
            "dirty": False,
            "dirty_count": 0,
            "ahead": 0,
            "behind": 0,
            "detached": False,
            "last_commit": {"sha": "", "date": "", "author": "", "message": ""},
            "branch_ok": False,
            "exists": False,
            "issues": ["Project directory missing"],
            "open_prs": 0,
            "prs": [],
        }

    branch = _get_current_branch(name, root)
    tracking = _get_tracking_branch(name, root)
    deploy = _get_deploy_branch(name, root)
    dirty = _is_dirty(name, root)
    dirty_count = _get_dirty_count(name, root)
    ahead, behind = _get_ahead_behind(name, root)
    last_commit = _get_last_commit(name, root)
    prs = _get_open_prs(name, root, deploy)
    detached = branch == "HEAD"

    # Branch alignment: ok if no tracking configured, or matches
    branch_ok = (not tracking) or (branch == tracking)
    # Aligned: current branch matches deploy branch
    aligned = (branch == deploy) and not detached

    # Build human-readable issues list
    issues: list[str] = []
    if detached:
        issues.append("Detached HEAD")
    if dirty:
        issues.append(f"Dirty working tree ({dirty_count} files)")
    if not branch_ok:
        issues.append(f"Branch mismatch: {branch} (expected {tracking})")
    if not aligned and not detached:
        issues.append(f"Not on deploy branch {deploy} (on {branch})")
    if behind > 0:
        issues.append(f"Behind remote by {behind} commits")

    return {
        "name": name,
        "branch": branch,
        "tracking_branch": tracking,
        "deploy_branch": deploy,
        "aligned": aligned,
        "dirty": dirty,
        "dirty_count": dirty_count,
        "ahead": ahead,
        "behind": behind,
        "detached": detached,
        "last_commit": last_commit,
        "branch_ok": branch_ok,
        "exists": True,
        "issues": issues,
        "open_prs": len(prs),
        "prs": prs,
    }


def git_status_all(root: Optional[Path] = None) -> dict:
    """Collect git state for every registered submodule in a single call.

    Returns a dict with:

    - ``projects``: list of per-project status dicts, each containing:
      - ``name``: project name
      - ``branch``: current branch (or ``"HEAD"`` if detached)
      - ``tracking_branch``: expected branch from .gitmodules
      - ``deploy_branch``: deploy branch from config or fallback
      - ``aligned``: whether current branch matches deploy branch
      - ``dirty``: whether the working tree has uncommitted changes
      - ``dirty_count``: number of modified/untracked files
      - ``ahead``: commits ahead of remote
      - ``behind``: commits behind remote
      - ``detached``: whether HEAD is detached
      - ``last_commit``: dict with ``sha``, ``date``, ``author``, ``message``
      - ``branch_ok``: whether current branch matches tracking branch
      - ``exists``: whether the project directory exists
      - ``issues``: list of human-readable problem strings
      - ``open_prs``: number of open PRs targeting the deploy branch
      - ``prs``: list of open PR dicts (``number``, ``title``, ``branch``,
        ``draft``, ``updated``); empty when ``gh`` is unavailable
    - ``total``: number of registered projects
    - ``issues``: count of projects with any problem (dirty/misaligned/missing)
    - ``ok``: ``True`` if no projects have issues
    - ``summary``: human-readable summary string

    This is the single-command entry point for the hub git status dashboard.
    Git commands are run in parallel (one thread per project) for performance
    at 20+ repos.
    """
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return {
            "projects": [],
            "total": 0,
            "issues": 0,
            "ok": False,
            "summary": "Not a hub project.",
        }

    names = list(config.projects)
    if not names:
        return {
            "projects": [],
            "total": 0,
            "issues": 0,
            "ok": True,
            "summary": "No projects registered.",
        }

    # Collect status for all projects in parallel
    with ThreadPoolExecutor(max_workers=min(len(names), 16)) as pool:
        results = list(pool.map(lambda n: _collect_project_status(n, root), names))

    # Preserve registration order
    projects = results
    issue_count = sum(
        1 for p in projects
        if p["dirty"] or not p["branch_ok"] or p["behind"] > 0 or not p["exists"]
    )

    total = len(projects)
    if issue_count == 0:
        summary = f"All {total} projects clean."
    else:
        summary = f"{issue_count}/{total} projects need attention."

    return {
        "projects": projects,
        "total": total,
        "issues": issue_count,
        "ok": issue_count == 0,
        "summary": summary,
    }


def _severity_score(project: dict) -> int:
    """Return a sort key for attention-priority ordering.

    Lower score = needs more attention (sorts first).
    """
    if not project.get("exists", True):
        return 0  # missing dir — highest severity
    if project.get("detached"):
        return 1
    if not project.get("branch_ok"):
        return 2
    if project.get("dirty"):
        return 3
    if project.get("behind", 0) > 0:
        return 4
    if not project.get("aligned"):
        return 5
    if project.get("ahead", 0) > 0:
        return 6
    return 10  # clean — sorts last


def format_git_status(data: dict, *, verbose: bool = False) -> str:
    """Render ``git_status_all()`` output as a compact, scannable table.

    Args:
        data: dict returned by ``git_status_all()``.
        verbose: If True, include last commit info, PR titles, and dirty file
            details.

    Returns:
        Multi-line formatted string ready for terminal output.
    """
    projects = data.get("projects", [])
    total = data.get("total", 0)

    if total == 0:
        return data.get("summary", "No projects.")

    # Sort by severity (most attention-needing first)
    sorted_projects = sorted(projects, key=_severity_score)

    # Column headers
    header = ["Project", "Branch", "Deploy", "Dirty", "Ahead/Behind", "PRs", "Issues"]

    # Build rows
    rows: list[list[str]] = []
    for p in sorted_projects:
        name = p["name"]
        branch = f"({p['branch']})" if p.get("detached") else p.get("branch", "")
        deploy = p.get("deploy_branch", "main")
        dirty = f"{p['dirty_count']} mod" if p.get("dirty") else ""
        ahead = p.get("ahead", 0)
        behind = p.get("behind", 0)
        ab = f"{ahead}/{behind}" if (ahead or behind) else ""
        prs = str(p.get("open_prs", 0)) if p.get("open_prs") else ""

        # Issues column: compact summary
        issues = p.get("issues", [])
        if issues:
            # Show first issue inline, rest in verbose
            issue_str = issues[0] if len(issues) == 1 else f"{len(issues)} issues"
        else:
            issue_str = ""

        rows.append([name, branch, deploy, dirty, ab, prs, issue_str])

    # Calculate column widths
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # Format output
    lines: list[str] = []
    lines.append(f"Hub Git Status ({total} projects)\n")

    # Header line
    hdr = "  ".join(h.ljust(widths[i]) for i, h in enumerate(header))
    lines.append(f"  {hdr}")

    # Rows
    for row in rows:
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(f"  {line}")

    # Verbose details
    if verbose:
        lines.append("")
        for p in sorted_projects:
            if not p.get("exists"):
                lines.append(f"  {p['name']}: MISSING — project directory not found")
                continue
            commit = p.get("last_commit", {})
            if commit.get("sha"):
                lines.append(
                    f"  {p['name']}: {commit['sha'][:8]} "
                    f"{commit.get('date', '')} "
                    f"({commit.get('author', '')}) "
                    f"{commit.get('message', '')}"
                )
            pr_list = p.get("prs", [])
            for pr in pr_list:
                draft = " [draft]" if pr.get("draft") else ""
                lines.append(
                    f"    PR #{pr['number']}: {pr['title']} "
                    f"({pr['branch']}){draft}"
                )
            issues = p.get("issues", [])
            for issue in issues:
                lines.append(f"    ! {issue}")

    # Summary footer
    lines.append("")
    issue_count = data.get("issues", 0)
    if issue_count:
        lines.append(
            f"{issue_count} issue{'s' if issue_count != 1 else ''} found. "
            f"Run `projectman git-status --verbose` for details."
        )
    else:
        lines.append(f"All {total} projects clean.")

    return "\n".join(lines)
