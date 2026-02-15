"""Hub registry — manage subproject registration via git submodules."""

import subprocess
from pathlib import Path
from typing import Optional

import yaml

from ..config import load_config, save_config


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

    # Initialize .project/ in the submodule if it doesn't have one
    if not (target / ".project" / "config.yaml").exists():
        _init_subproject(target, name)

    # Register in config
    if name not in config.projects:
        config.projects.append(name)
        save_config(config, root)

    msg = f"added project '{name}' from {git_url}"
    if branch:
        msg += f" (branch: {branch})"
    msg += f"\n\nRun /pm-init {name} to set up project documentation."
    return msg


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


def repair(root: Optional[Path] = None) -> str:
    """Scan the hub, fix missing pieces, import existing data, rebuild indexes.

    1. Discover unregistered projects in projects/ directory
    2. Initialize .project/ where missing
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

    # 2. Initialize .project/ where missing, rebuild indexes where present
    initialized = []
    rebuilt = []
    story_counts = {}

    for name in config.projects:
        project_path = projects_dir / name
        if not project_path.exists():
            report_lines.append(f"- **{name}** — directory missing, skipped")
            continue

        if not (project_path / ".project" / "config.yaml").exists():
            _init_subproject(project_path, name)
            initialized.append(name)
        else:
            # Project exists and has .project/ — quarantine bad files, rebuild index
            try:
                import frontmatter as fm
                from ..models import StoryFrontmatter, TaskFrontmatter
                import shutil

                store = Store(project_path)
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
                        report_lines.append(f"- `{fname}` → `.project/malformed/{fname}`: {err}")
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

    # 3. Rebuild hub embeddings from all subprojects
    embedded_count = 0
    try:
        from ..embeddings import EmbeddingStore

        hub_proj_dir = root / ".project"
        emb_store = EmbeddingStore(hub_proj_dir)

        for name in config.projects:
            project_path = projects_dir / name
            if not (project_path / ".project" / "config.yaml").exists():
                continue

            try:
                store = Store(project_path)
                sub_config = store.config

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

    # 4. Regenerate hub dashboards
    try:
        from .dashboards import generate_dashboards
        generate_dashboards(root)
        report_lines.append("## Regenerated hub dashboards\n")
        report_lines.append("- Updated status.md and burndown.md")
        report_lines.append("")
    except Exception as e:
        report_lines.append(f"## Dashboard generation failed: {e}\n")

    # 5. Save config if changed
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
        has_project_dir = (project_path / ".project").exists()
        results.append({
            "name": name,
            "path": str(project_path),
            "exists": project_path.exists(),
            "initialized": has_project_dir,
        })

    return results
