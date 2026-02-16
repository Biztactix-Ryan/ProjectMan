"""Hub registry — manage subproject registration via git submodules."""

import re
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from ..config import load_config, save_config


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
    pm_dir = root / ".project" / "projects" / name
    if not (pm_dir / "config.yaml").exists():
        _init_subproject(pm_dir, name, repo=repo)

    # Register in config
    if name not in config.projects:
        config.projects.append(name)
        save_config(config, root)

    msg = f"added project '{name}' from {git_url}"
    if branch:
        msg += f" (branch: {branch})"
    msg += f"\n\nRun /pm-init {name} to set up project documentation."
    return msg


def _init_subproject(target: Path, name: str, repo: str = "") -> None:
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
        ctx = dict(name=name, prefix=prefix, description="", repo=repo, hub=False)

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
        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(target),
                check=True,
                capture_output=True,
                text=True,
            )
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
    return summary + "\n" + "\n".join(results)


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
