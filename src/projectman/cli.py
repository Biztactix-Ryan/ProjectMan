"""ProjectMan CLI — Click-based command interface."""

import json
import shutil
from pathlib import Path

import click
import yaml
from jinja2 import Environment, FileSystemLoader

# Template loading helper
def _template_dir() -> Path:
    """Get the templates directory from the package."""
    import importlib.resources
    return Path(str(importlib.resources.files("projectman") / "templates"))


def _render_template(template_name: str, **kwargs) -> str:
    """Render a Jinja2 template by name."""
    tdir = _template_dir()
    env = Environment(loader=FileSystemLoader(str(tdir)), keep_trailing_newline=True)
    try:
        tmpl = env.get_template(template_name)
        return tmpl.render(**kwargs)
    except Exception:
        return f"# {template_name} — template not found\n"


@click.group()
def cli():
    """ProjectMan — git-native project management."""
    pass


def _attachable_root(start: Path, branch: str = "projectman"):
    """The repo root when `start` is a clone whose PM store wants attaching.

    Returns None — meaning "scaffold as usual" — unless all of:

    * `start` is inside a git repo;
    * that repo knows `origin/<branch>` or a local `<branch>` branch (local ref
      storage only: this never fetches, exactly like `projectman attach`);
    * the repo root's `<root>/.project` is absent, an empty directory, or
      already a git worktree (the friendly no-op case).

    A `.project/` that is a plain directory with content — or a file — is left
    to the scaffolding path's "already exists" refusal, so an unmigrated store
    is never mounted over.
    """
    from projectman.worktree import (
        MigrationError,
        branch_exists,
        is_worktree,
        remote_branch_exists,
        repo_root,
    )

    try:
        root = repo_root(start)
    except MigrationError:
        return None
    if not (remote_branch_exists(root, branch) or branch_exists(root, branch)):
        return None

    target = root / ".project"
    if is_worktree(target):
        return root
    if not target.exists():
        return root
    if target.is_dir() and not any(target.iterdir()):
        return root
    return None


def _init_attach(root: Path, name, prefix, description, hub, branch: str = "projectman") -> None:
    """Run the attach flow from `init`, reporting why and what was ignored.

    Exits 1 with the attach refusal on stderr when the mount cannot be made;
    scaffolding is never attempted as a fallback, because a `projectman`
    branch means the store exists and a second one would be wrong.
    """
    from projectman.worktree import (
        MigrationError,
        attach_worktree,
        format_attach_result,
        remote_branch_exists,
    )

    found = (
        f"origin/{branch}"
        if remote_branch_exists(root, branch)
        else f"local branch '{branch}'"
    )
    click.echo(
        f"Found {found} — attaching the existing PM store instead of "
        "scaffolding a new one."
    )

    ignored = [
        flag
        for flag, passed in (
            ("--name", name is not None),
            ("--prefix", prefix != "PRJ"),
            ("--description", bool(description)),
            ("--hub", hub),
        )
        if passed
    ]
    for flag in ignored:
        click.echo(f"{flag} ignored: attaching existing store", err=True)

    try:
        result = attach_worktree(root, branch=branch)
    except MigrationError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(format_attach_result(result))


@cli.command()
@click.option("--name", default=None, help="Name for the project (prompted when a store is scaffolded)")
@click.option("--prefix", default="PRJ", help="ID prefix (uppercase letters)")
@click.option("--description", default="", help="Project description")
@click.option("--hub", is_flag=True, help="Initialize as hub (multi-repo)")
@click.option("--no-attach", "no_attach", is_flag=True, help="Scaffold a fresh store even when a projectman branch exists")
def init(name, prefix, description, hub, no_attach):
    """Initialize a new .project/ directory — or attach an existing store.

    On a fresh clone of a repo whose PM state lives on the `projectman` branch
    (see `projectman migrate-worktree`), there is nothing to scaffold: the
    store already exists, it just is not mounted. So init first looks for a
    `projectman` branch — `origin/projectman` or a local one, read from local
    ref storage only, never fetched — and when it finds one it runs the
    `projectman attach` flow instead, mounting `.project/` as a worktree of
    that branch. No new files are written and .gitignore is left alone.

    `.project/` already being a worktree of the branch is a friendly no-op
    (exit 0) rather than the "already exists" error, so re-running init on a
    clone is safe. A `.project/` that is a plain directory with content still
    gets the "already exists" refusal (exit 1, nothing touched).

    Without such a branch — including outside a git repo — the scaffolding is
    exactly as it always was. `--no-attach` forces that path even when the
    branch exists. In the attach case --prefix/--description/--hub/--name
    describe a store that is not being created, so they are ignored with a
    warning.
    """
    root = Path.cwd()
    proj = root / ".project"

    attach_root = None if no_attach else _attachable_root(root)
    if attach_root is not None:
        _init_attach(attach_root, name, prefix, description, hub)
        return

    if proj.exists():
        click.echo("Error: .project/ already exists", err=True)
        raise SystemExit(1)

    if name is None:
        name = click.prompt("Project name")

    # Create directory structure
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "epics").mkdir()

    if hub:
        # Subproject checkouts sit beside the hub store, not inside it: each
        # one carries its own .project/ (US-PM-31).
        from projectman.hub.stores import projects_dir

        projects_dir(root).mkdir(exist_ok=True)
        (proj / "roadmap").mkdir()
        (proj / "dashboards").mkdir()

    ctx = dict(name=name, prefix=prefix, description=description, hub=hub)

    # Write config
    config_content = _render_template("config.yaml.j2", **ctx)
    (proj / "config.yaml").write_text(config_content)

    # Write documentation files
    (proj / "PROJECT.md").write_text(_render_template("project.md.j2", **ctx))
    (proj / "INFRASTRUCTURE.md").write_text(_render_template("infrastructure.md.j2", **ctx))
    (proj / "SECURITY.md").write_text(_render_template("security.md.j2", **ctx))

    # Write empty index
    empty_index = {
        "entries": [],
        "total_points": 0,
        "completed_points": 0,
        "story_count": 0,
        "task_count": 0,
        "epic_count": 0,
    }
    with open(proj / "index.yaml", "w") as f:
        yaml.dump(empty_index, f, default_flow_style=False)

    # ...and keep it, and the four markdown indexes, out of git. They are
    # derived from the item files and rebuilt on demand (US-PM-29); tracking
    # them would put an index echo in every commit that touches an item.
    from .indexer import write_store_gitignore

    write_store_gitignore(proj)

    # Hub context docs
    if hub:
        (proj / "VISION.md").write_text(_render_template("vision.md.j2", **ctx))
        (proj / "ARCHITECTURE.md").write_text(_render_template("architecture_hub.md.j2", **ctx))
        (proj / "DECISIONS.md").write_text(_render_template("decisions.md.j2", **ctx))

    click.echo(f"Initialized project '{name}' in .project/")
    if hub:
        click.echo("Hub mode enabled — use 'projectman add-project' to register repos")


# Skills distributed by setup-claude. /pm is the smart router; the rest are
# focused workflows. Keep this list in sync with the skill_*.md.j2 templates.
CLAUDE_SKILLS = [
    ("pm", "skill_pm.md.j2"),
    ("pm-status", "skill_pm_status.md.j2"),
    ("pm-plan", "skill_pm_plan.md.j2"),
    ("pm-do", "skill_pm_do.md.j2"),
    ("pm-orchestrate", "skill_pm_orchestrate.md.j2"),
    ("pm-autoscope", "skill_pm_autoscope.md.j2"),
    ("pm-cleanup", "skill_pm_cleanup.md.j2"),
    ("pm-next", "skill_pm_next.md.j2"),
]

# Skills from older versions that were folded into /pm — removed on install.
STALE_SKILLS = ["pm-scope", "pm-audit", "pm-fix", "pm-init"]


def _write_claude_assets(claude_dir: Path) -> None:
    """Write the pm agent and skills into a .claude/ directory."""
    agents_dir = claude_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "pm.md").write_text(_render_template("agent_pm.md.j2"))
    click.echo(f"Wrote {agents_dir / 'pm.md'}")

    for stale in STALE_SKILLS:
        stale_dir = claude_dir / "skills" / stale
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
            click.echo(f"Removed stale {stale_dir}/")

    for skill_name, template_name in CLAUDE_SKILLS:
        skill_dir = claude_dir / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(_render_template(template_name))
        click.echo(f"Wrote {skill_dir / 'SKILL.md'}")


@cli.command("setup-claude")
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="MCP transport mode (default: stdio)")
@click.option("--host", default="127.0.0.1", help="Host for SSE mode")
@click.option("--port", default=22001, type=int, help="Port for SSE mode")
@click.option("--global", "global_", is_flag=True, help="Install agent + skills to ~/.claude for all projects (registers MCP at user scope via the claude CLI)")
@click.option("--local-skills", is_flag=True, help="With --global: also write skill copies into the current project's .claude/")
def setup_claude(transport, host, port, global_, local_skills):
    """Install Claude Code integration (agent, skills, MCP config).

    Default: project-level install — writes .mcp.json and .claude/ in the
    current directory. With --global: installs to ~/.claude so every project
    gets the skills, and registers the MCP server at user scope.
    """
    root = Path.cwd()

    if global_:
        import subprocess

        _write_claude_assets(Path.home() / ".claude")

        # Register the MCP server at user scope via the claude CLI.
        if transport == "sse":
            mcp_cmd = ["claude", "mcp", "add", "--scope", "user", "--transport", "sse", "projectman", f"http://{host}:{port}/sse"]
        else:
            mcp_cmd = ["claude", "mcp", "add", "--scope", "user", "projectman", "--", "projectman", "serve"]

        if shutil.which("claude"):
            result = subprocess.run(mcp_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                click.echo("Registered projectman MCP server at user scope.")
            else:
                click.echo(f"claude mcp add failed: {result.stderr.strip()}", err=True)
                click.echo(f"Register manually with: {' '.join(mcp_cmd)}")
        else:
            click.echo(f"claude CLI not found — register the MCP server manually with: {' '.join(mcp_cmd)}")

        if local_skills:
            _write_claude_assets(root / ".claude")

        click.echo("Global Claude Code integration installed. Restart Claude Code to activate.")
        return

    # Project-level install: .mcp.json + .claude/ in the current directory.
    if transport == "sse":
        mcp_config = {
            "mcpServers": {
                "projectman": {
                    "type": "sse",
                    "url": f"http://{host}:{port}/sse",
                }
            }
        }
    else:
        mcp_config = {
            "mcpServers": {
                "projectman": {
                    "command": "projectman",
                    "args": ["serve"],
                    "type": "stdio",
                }
            }
        }
    mcp_path = root / ".mcp.json"
    # Merge with existing if present
    if mcp_path.exists():
        with open(mcp_path) as f:
            existing = json.load(f)
        existing.setdefault("mcpServers", {}).update(mcp_config["mcpServers"])
        mcp_config = existing
    with open(mcp_path, "w") as f:
        json.dump(mcp_config, f, indent=2)
    click.echo("Wrote .mcp.json")

    _write_claude_assets(root / ".claude")

    click.echo("Claude Code integration installed. Restart Claude Code to activate.")


def _remove_claude_assets(claude_dir: Path) -> None:
    """Remove the ProjectMan-managed agent + skills from a .claude/ directory.

    Only touches files this tool wrote (agents/pm.md, skills/pm*); other
    agents and skills are left alone. Empty parent dirs are cleaned up.
    """
    agent = claude_dir / "agents" / "pm.md"
    if agent.exists():
        agent.unlink()
        click.echo(f"Removed {agent}")

    for skill_name, _ in CLAUDE_SKILLS:
        skill_dir = claude_dir / "skills" / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            click.echo(f"Removed {skill_dir}/")
    for stale in STALE_SKILLS:
        stale_dir = claude_dir / "skills" / stale
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
            click.echo(f"Removed stale {stale_dir}/")

    for parent in (claude_dir / "agents", claude_dir / "skills"):
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


@cli.command("refresh-skills")
@click.option("--keep-local", is_flag=True, help="Keep project-local pm skill copies even when the same skills are installed globally in ~/.claude (they are pruned as duplicates by default)")
def refresh_skills(keep_local):
    """Rewrite the pm agent + skills wherever they are already installed.

    Checks ~/.claude and the current directory's .claude/ and re-renders the
    ProjectMan-managed files (agents/pm.md, skills/pm*) from the installed
    package's templates. Use setup-claude to install into a new location.

    If the skills are installed both globally and in the current project,
    the local copies are superseded — Claude Code loads both and shows
    duplicates — so the local copies are removed (pass --keep-local to
    keep and refresh them instead).
    """
    global_dir = Path.home() / ".claude"
    local_dir = Path.cwd() / ".claude"
    has_global = (global_dir / "skills" / "pm" / "SKILL.md").exists()
    has_local = (
        local_dir.resolve() != global_dir.resolve()
        and (local_dir / "skills" / "pm" / "SKILL.md").exists()
    )

    if not has_global and not has_local:
        click.echo(
            "No installed pm skills found in ~/.claude or ./.claude — "
            "run 'projectman setup-claude' (optionally --global) first."
        )
        return

    if has_global and has_local and not keep_local:
        click.echo(
            f"Local pm skills in {local_dir} are superseded by the global install "
            "in ~/.claude (Claude Code loads both and shows duplicates) — removing local copies."
        )
        _remove_claude_assets(local_dir)
        has_local = False

    targets = []
    if has_global:
        targets.append(global_dir)
    if has_local:
        targets.append(local_dir)
    for target in targets:
        _write_claude_assets(target)
    click.echo(f"Refreshed pm skills in: {', '.join(str(t) for t in targets)}")
    click.echo("Restart Claude Code (or start a new session) to pick up the updated skills.")


PROJECTMAN_REPO = "git+https://github.com/Biztactix-Ryan/ProjectMan"


@cli.command()
@click.option("--check", is_flag=True, help="Show the installed version and pipx source without upgrading")
@click.option("--no-skills", is_flag=True, help="Skip refreshing installed Claude skills after the upgrade")
def upgrade(check, no_skills):
    """Upgrade projectman via pipx (or check the installed version).

    After a successful upgrade, installed pm skills (in ~/.claude and the
    current directory's .claude/) are re-rendered from the new version's
    templates so tools and skills stay in sync.
    """
    import subprocess
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        current = _pkg_version("projectman")
    except PackageNotFoundError:
        current = "unknown"
    click.echo(f"Installed version: {current}")

    pipx = shutil.which("pipx")
    if not pipx:
        click.echo(f"pipx not found — install/upgrade with: pipx install --force '{PROJECTMAN_REPO}' (or your original install method)", err=True)
        raise SystemExit(1)

    def _pipx_metadata():
        result = subprocess.run([pipx, "list", "--json"], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            venvs = json.loads(result.stdout).get("venvs", {})
            return venvs.get("projectman", {}).get("metadata", {}).get("main_package", {})
        except (json.JSONDecodeError, AttributeError):
            return None

    meta = _pipx_metadata()
    if not meta:
        click.echo(f"projectman is not managed by pipx — reinstall with: pipx install '{PROJECTMAN_REPO}', or upgrade with your original install method.", err=True)
        raise SystemExit(1)

    click.echo(f"pipx source: {meta.get('package_or_url', 'unknown')}")
    if check:
        click.echo("Run 'projectman upgrade' to upgrade from that source.")
        return

    result = subprocess.run([pipx, "upgrade", "projectman"], text=True)
    if result.returncode != 0:
        click.echo("pipx upgrade failed.", err=True)
        raise SystemExit(1)

    meta = _pipx_metadata() or {}
    new_version = meta.get("package_version", "unknown")
    if new_version == current:
        click.echo(f"Already up to date ({current}).")
    else:
        click.echo(f"Upgraded {current} → {new_version}. Restart any running MCP servers to pick up the new version.")

    if not no_skills:
        # Re-render installed skills from the NEW package's templates. This
        # process still runs the pre-upgrade code, so the refresh must be
        # executed by the upgraded binary.
        exe = shutil.which("projectman")
        if exe:
            refresh = subprocess.run([exe, "refresh-skills"], text=True)
            if refresh.returncode != 0:
                click.echo("Skill refresh failed — run 'projectman refresh-skills' manually.", err=True)
        else:
            click.echo("projectman executable not found on PATH — run 'projectman refresh-skills' manually to update skills.")


@cli.command()
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="Transport mode (default: stdio)")
@click.option("--host", default="127.0.0.1", help="Host to bind to (SSE mode only)")
@click.option("--port", default=22001, type=int, help="Port to bind to (SSE mode only)")
def serve(transport, host, port):
    """Start the MCP server."""
    try:
        from projectman.server import run_server
        run_server(transport=transport, host=host, port=port)
    except ImportError:
        click.echo("Error: MCP extras not installed. Run: pip install projectman[mcp]", err=True)
        raise SystemExit(1)


@cli.command("add-project")
@click.argument("name")
@click.argument("git_url")
@click.option("--branch", "-b", default=None, help="Branch to track (default: remote HEAD)")
def add_project(name, git_url, branch):
    """Add a project submodule to the hub."""
    from projectman.hub.registry import add_project as _add
    result = _add(name, git_url, branch=branch)
    click.echo(result)


@cli.command("set-branch")
@click.argument("name")
@click.argument("branch")
def set_branch(name, branch):
    """Change the branch a hub submodule tracks."""
    from projectman.hub.registry import set_branch as _set_branch
    result = _set_branch(name, branch)
    click.echo(result)


@cli.command()
def sync():
    """Pull latest from all hub submodules (fast-forward only, skips dirty repos)."""
    from projectman.hub.registry import sync as _sync
    result = _sync()
    click.echo(result)


@cli.command()
@click.option("--project", default=None, help="Project name (hub mode only)")
def reindex(project):
    """Regenerate index.yaml and the four markdown indexes from the item files.

    One of the three rebuild points for the derived indexes (US-PM-29); the
    other two are the ``pm_reindex`` tool and ``projectman commit``, which
    rebuilds immediately before staging.
    """
    from projectman.config import find_project_root, load_config
    from projectman.indexer import write_index
    from projectman.store import Store

    root = find_project_root()

    if project:
        config = load_config(root)
        if not config.hub:
            click.echo("Error: --project is hub mode only", err=True)
            raise SystemExit(1)
        from projectman.hub.stores import attached_store_path

        try:
            project_dir = attached_store_path(root, project)
        except FileNotFoundError:
            click.echo(f"Error: project '{project}' not found in hub", err=True)
            raise SystemExit(1)
        store = Store(root, project_dir=project_dir)
    else:
        store = Store(root)

    write_index(store)
    click.echo(f"Reindexed: {store.project_dir}")


def _prefix_for_project(name):
    """Translate the break-glass CLI's ``--project NAME`` into a store prefix.

    The tools address a store by the prefix inside its IDs (US-PM-34), but a
    human recovering a broken project knows its *name* — the directory they
    are standing next to — and should not have to look the prefix up. Outside
    a hub there is one store and nothing to translate.
    """
    if not name:
        return None
    from projectman.config import find_project_root, load_config
    from projectman.hub.stores import hub_stores

    root = find_project_root()
    if not load_config(root).hub:
        click.echo("Error: --project is hub mode only", err=True)
        raise SystemExit(1)
    for entry in hub_stores(root):
        if entry["name"] == name:
            return entry.get("prefix")
    click.echo(f"Error: project '{name}' not found in hub", err=True)
    raise SystemExit(1)


def _store_dir_for_prefix(root, prefix):
    """The one store ``projectman commit`` / ``push`` should act on.

    The same rule the MCP verbs use, and the same resolver:
    :func:`projectman.server._hub_entry_for_prefix` — no prefix means the
    hub's own store, a prefix names one subproject's store, and an unknown
    prefix is the coded ``not_found`` listing the prefixes that do exist.
    Only called in a hub; outside one there is a single store and nothing to
    resolve.
    """
    from projectman.hub.stores import hub_store_dir
    from projectman.server import _hub_entry_for_prefix

    try:
        entry = _hub_entry_for_prefix(prefix)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    return entry["path"] if entry else hub_store_dir(root)


def _break_glass(fn, **kwargs) -> str:
    """Run one break-glass server function and turn its failure into exit 1.

    The ``maintenance`` tool family (``pm_restore``, ``pm_fix_malformed``) is
    hidden from the agent tool list by default — see
    ``server.TOOL_FAMILIES`` — because recovering a broken project is a
    human action.  Hidden is not gone: these commands call the very same
    functions, so the CLI stays the supported way in (US-PM-15-6).
    """
    try:
        return fn(**kwargs)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("filename")
@click.option("--project", default=None, help="Project name (hub mode only)")
def restore(filename, project):
    """Move a fixed file out of malformed/ back into stories/ or tasks/."""
    from projectman import server

    click.echo(
        _break_glass(
            server.pm_restore, filename=filename, prefix=_prefix_for_project(project)
        )
    )


@cli.command("fix-malformed")
@click.argument("filename")
@click.option("--id", "id_", required=True, help="Correct item ID (e.g. PRJ-1, PRJ-1-1)")
@click.option("--title", required=True, help="Correct title")
@click.option("--type", "item_type", type=click.Choice(["story", "task"]), required=True, help="Item type")
@click.option("--body", default=None, help="New body content (keeps the original if omitted)")
@click.option("--status", default=None, help="Status (stories: backlog/ready/active/done; tasks: todo/in-progress/review/done/blocked)")
@click.option("--priority", default=None, help="Priority for stories (must/should/could/wont)")
@click.option("--points", default=None, type=int, help="Story points")
@click.option("--story-id", default=None, help="Parent story ID (required for tasks)")
@click.option("--project", default=None, help="Project name (hub mode only)")
def fix_malformed(filename, id_, title, item_type, body, status, priority, points, story_id, project):
    """Rewrite a quarantined file with valid frontmatter and restore it."""
    from projectman import server

    click.echo(
        _break_glass(
            server.pm_fix_malformed,
            filename=filename,
            id=id_,
            title=title,
            item_type=item_type,
            body=body,
            status=status,
            priority=priority,
            points=points,
            story_id=story_id,
            prefix=_prefix_for_project(project),
        )
    )


@cli.command("migrate-archived")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Write the changes. Without this flag the command only reports.",
)
@click.option("--project", default=None, help="Project name (hub mode only)")
def migrate_archived(apply_changes, project):
    """Restore archived flags the log recorded but the task files have lost.

    Identification needs a positive archive signal in the log; a status
    footprint is never enough. Applying sets the archived flag, and restores a
    status only when the archive event itself recorded one — the migration
    never moves a task out of 'done' on inferred evidence. Tasks that merely
    look archive-shaped are listed under manual review and never written.

    Reports only by default; pass --apply to rewrite the task files.
    """
    from projectman.config import find_project_root
    from projectman.migrations import format_report, migrate_archived_as_done
    from projectman.store import Store

    root = find_project_root()
    if project:
        from projectman.hub.stores import store_path

        store = Store(root, project_dir=store_path(root, project))
    else:
        store = Store(root)

    report = migrate_archived_as_done(store, apply=apply_changes)
    click.echo(format_report(report))


@cli.command("migrate-worktree")
@click.option("--branch", default="projectman", help="Orphan branch to create and mount (default: projectman)")
@click.option("--no-push", "no_push", is_flag=True, help="Migrate locally only; never push, even when an origin remote exists")
def migrate_worktree(branch, no_push):
    """Move .project/ onto an orphan branch mounted as a worktree.

    One-time migration. It creates an empty orphan `projectman` branch (root
    commit "ProjectMan root"), untracks .project on the current branch, adds a
    `.project/` entry to .gitignore, commits that, then mounts the branch at
    .project with `git worktree add` and commits the PM files there.

    The PM files are stashed to a temp directory for the swap and are only
    deleted once the worktree commit has succeeded; any failure puts them back.

    It refuses (exit 1, nothing changed) when the branch already exists locally
    or as origin/<branch> — use `projectman attach` for that — when .project/ is
    already a worktree or missing, or when the working tree is dirty. Dirty
    means a staged or unstaged change to a tracked file anywhere, or an
    untracked file under .project/ when .project is already partly tracked;
    untracked files elsewhere are left alone and do not block.

    \b
    Remote handling
    ---------------
    When an `origin` remote is configured, the new branch is pushed with
    `git push -u origin <branch>` twice: once right after the branch is created
    and once after the import commit, so origin/<branch> ends at the import
    commit and the local branch tracks it. Only that branch is pushed — the
    commit made on your current branch is yours to push.

    A failure of the *first* push is fatal: the branch is deleted and nothing is
    migrated, so you can fix the remote and re-run (or use --no-push). A failure
    of the *second* push leaves the finished local migration alone and only
    warns — re-run `git -C .project push` when the remote is reachable.

    With no origin remote the pushes are skipped with an informational message
    and the migration still succeeds. `--no-push` skips them even when a remote
    exists.

    \b
    Snapshot import vs. history-preserving import
    ---------------------------------------------
    Snapshot import is the default and the only mode this command implements:
    the projectman branch starts from an empty root commit and gets one commit
    holding .project/ as it stands now. The history of those files stays where
    it always was, on the branch you migrated from.

    To carry that history across instead, use the history-preserving variant
    from ADR-001 ("Store PM data on an orphan branch mounted as a worktree", in
    .project/DECISIONS.md), which records: "Migration is a snapshot import by
    default; `git filter-repo --subdirectory-filter .project` is the
    history-preserving variant." Run that filter on a clone to rewrite it down
    to just .project/, push the result as the projectman branch, then use
    `projectman attach` to mount it instead of running this command.
    """
    from projectman.worktree import MigrationError, format_result, migrate_to_worktree

    try:
        result = migrate_to_worktree(Path.cwd(), branch=branch, push=not no_push)
    except MigrationError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(format_result(result))


@cli.command("migrate-hub")
@click.option("--no-push", "no_push", is_flag=True, help="Migrate locally only; never push, even when a subproject has an origin remote")
@click.option("--dry-run", "dry_run", is_flag=True, help="Check every precondition and report the plan without changing anything")
def migrate_hub(no_push, dry_run):
    """Move PM data out of the hub, and subproject epics up into it.

    One-time migration for a hub built before the store moved. Per-project PM
    data used to live inside the hub's own store, so every task edit in every
    project became a commit on the hub repo. It now lives at
    projects/{name}/.project — a git worktree of that submodule's `projectman`
    branch, the same layout `projectman add-project` creates today.

    For each registered project that still has data in the hub, this attaches
    the submodule's existing `projectman` branch (or creates the orphan branch
    when there is none), copies the store across byte for byte, and commits it
    there with a message naming where it came from. Then, once, it `git rm -r`s
    the hub's copies and commits that removal on the hub.

    \b
    Then the epics
    --------------
    Epics live at hub level only, so a second half runs after the store move:
    every epics/EPIC-{PROJECT}-N.md left in a subproject store moves into the
    hub's .project/epics/ under a fresh hub-prefixed ID from the hub's own
    counter, and every story in every store that linked to one — including a
    story in one subproject pointing at an epic that lived in another — has
    its epic_id rewritten. Each changed store is committed inside itself, with
    the old-to-new mapping in the message, and that mapping is printed.

    The halves are independent: a hub whose stores are already at
    projects/{name}/.project gets just the epics step, so this is still the
    command to run after the store move is long done.

    \b
    Refusals — checked before the first change, so nothing is half-migrated
    -----------------------------------------------------------------------
    It exits 1 without touching anything when the hub's working tree is dirty,
    when any affected submodule's tree is dirty (same rule as
    `projectman migrate-worktree`: a staged or unstaged change to a tracked
    file), when an already-mounted subproject store the epics step would
    commit in has uncommitted changes, when a submodule is not checked out, or
    when a submodule's `projectman` branch already carries a store of its own —
    merging two PM stores is not a call this command makes.

    A hub with nothing left to move — no store in the old place and no
    subproject epic — says so and exits 0, so re-running is safe. Use
    --dry-run to check the preconditions and see the plan and the epic mapping
    first; it changes nothing, not even next_epic_id.

    Each `projectman` branch is pushed with `git push -u origin projectman`
    when the subproject has an origin remote; --no-push skips that. A push
    failure only warns — the local move is already complete. The hub's own
    commit and its updated submodule pointers are yours to push.
    """
    from projectman.hub.migrate import format_migration, migrate_hub as _migrate_hub
    from projectman.worktree import MigrationError

    try:
        results = _migrate_hub(Path.cwd(), push=not no_push, dry_run=dry_run)
    except MigrationError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(format_migration(results))


@cli.command("attach")
@click.option("--branch", default="projectman", help="Branch to mount at .project (default: projectman)")
def attach(branch):
    """Mount the projectman branch at .project — the fresh-clone counterpart.

    A clone of a migrated repo arrives with origin/projectman but no .project/,
    because the PM state lives on its own branch. This runs the git incantation
    that mounts it: `git worktree add --track -b projectman .project
    origin/projectman` when only the remote branch exists, or plain
    `git worktree add .project projectman` when the local branch is already
    there (it is never recreated).

    \b
    Idempotent and clobber-safe
    ---------------------------
    Attaching twice is fine: when .project/ is already a worktree of the branch
    the command says so and exits 0 without touching anything. It refuses (exit
    1, nothing changed) when .project/ is a worktree of a *different* branch, or
    when .project/ is a plain directory with content — that is either an
    unmigrated store, which wants `projectman migrate-worktree`, or files that
    are not ours to delete. An empty .project/ is fine and is mounted over.

    Only local refs are read — attach never fetches. If the branch was pushed
    since your last `git fetch origin`, fetch and re-run.
    """
    from projectman.worktree import MigrationError, attach_worktree, format_attach_result

    try:
        result = attach_worktree(Path.cwd(), branch=branch)
    except MigrationError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(format_attach_result(result))


@cli.command()
@click.option("--all", "audit_all", is_flag=True, help="Audit all projects in hub")
def audit(audit_all):
    """Run project audit and generate DRIFT.md."""
    from projectman.config import find_project_root, load_config
    from projectman.audit import run_audit
    root = find_project_root()

    if audit_all:
        config = load_config(root)
        if config.hub:
            from projectman.hub.stores import hub_stores

            from projectman.hub.stores import attach_hint
            from projectman.store import Store

            # Epics are hub-level (US-PM-36): a subproject story pointing at a
            # hub epic is a correct link, so every subproject audit is told
            # which epic IDs the hub owns.
            hub_epic_ids = {e.id for e in Store(root).list_epics()}

            for entry in hub_stores(root):
                if entry["attached"]:
                    click.echo(f"\n--- Auditing {entry['name']} ---")
                    click.echo(
                        run_audit(
                            root,
                            project_dir=entry["path"],
                            known_epic_ids=hub_epic_ids,
                        )
                    )
                else:
                    # Say what was skipped and why — a silent skip made
                    # "audited everything" untrue (US-PM-31-9).
                    click.echo(f"\n--- Skipping {entry['name']}: not attached ---")
                    click.echo(attach_hint(entry["name"]))
            return

    report = run_audit(root)
    click.echo(report)


@cli.command()
@click.option("--prefix", default=None, help="In a hub, the prefix of the project to commit (default: the hub's own store). Ignored outside a hub")
@click.option("--message", "-m", default=None, help="Commit message (auto-generated if omitted)")
def commit(prefix, message):
    """Commit .project/ changes with auto-generated message."""
    from projectman.config import find_project_root, load_config
    from projectman.store import Store

    root = find_project_root()
    config = load_config(root)

    if config.hub:
        from projectman.hub.registry import pm_commit
        try:
            result = pm_commit(_store_dir_for_prefix(root, prefix), message=message)
        except (ValueError, FileNotFoundError) as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        if result.get("nothing_to_commit"):
            click.echo("Nothing to commit.")
            return

        click.echo(f"Committed: {result['commit_hash'][:8]}")
        if result.get("on_branch"):
            click.echo(f"Branch: {result['on_branch']}")
        click.echo(f"Message: {result['message']}")
        click.echo(f"Files ({len(result['files_committed'])}):")
        for f in result["files_committed"]:
            click.echo(f"  {f}")
    else:
        from projectman.indexer import write_index

        store = Store(root)
        # Rebuild the derived indexes immediately before staging (US-PM-29):
        # mutating tools no longer rewrite them on every write.
        write_index(store)
        try:
            result = store.commit_project_changes(message=message)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        click.echo(f"Committed: {result['commit_hash'][:8]}")
        if result.get("on_branch"):
            click.echo(f"Branch: {result['on_branch']}")
        click.echo(f"Message: {result['message']}")
        click.echo(f"Files ({len(result['files_changed'])}):")
        for f in result["files_changed"]:
            click.echo(f"  {f}")


@cli.command()
@click.option("--prefix", default=None, help="In a hub, the prefix of the project to push (default: the hub's own store). Ignored outside a hub")
def push(prefix):
    """Push committed .project/ changes to remote."""
    from projectman.config import find_project_root, load_config
    from projectman.store import Store

    root = find_project_root()
    config = load_config(root)

    if config.hub:
        from projectman.hub.registry import pm_push

        try:
            result = pm_push(_store_dir_for_prefix(root, prefix))
        except (RuntimeError, FileNotFoundError, ValueError) as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        click.echo(f"Pushed {result['branch']} to {result['remote']}")
    else:
        store = Store(root)
        try:
            result = store.push_project_changes()
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        click.echo(f"Pushed {result['branch']} to {result['remote']}")


@cli.command("git-status")
@click.option("--verbose", "-v", is_flag=True, help="Show commit info, PR titles, and dirty file details")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON (for MCP/script consumption)")
def git_status_cmd(verbose, as_json):
    """Show git state of all hub submodules in a compact table."""
    from projectman.hub.registry import git_status_all, format_git_status

    data = git_status_all()

    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        click.echo(format_git_status(data, verbose=verbose))

    raise SystemExit(0 if data.get("ok") else 1)


@cli.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
def web(port, host):
    """Start the ProjectMan web server."""
    try:
        import uvicorn
        from projectman.web.app import app
    except ImportError:
        click.echo(
            "Error: Web dependencies not installed.\n"
            "Install them with: pip install projectman[web]",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Starting ProjectMan Web on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


# Aliases: `projectman install` == `setup-claude`, `projectman update` == `upgrade`
cli.add_command(setup_claude, name="install")
cli.add_command(upgrade, name="update")
