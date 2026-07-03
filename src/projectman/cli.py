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


@cli.command()
@click.option("--name", prompt="Project name", help="Name for the project")
@click.option("--prefix", default="PRJ", help="ID prefix (uppercase letters)")
@click.option("--description", default="", help="Project description")
@click.option("--hub", is_flag=True, help="Initialize as hub (multi-repo)")
def init(name, prefix, description, hub):
    """Initialize a new .project/ directory."""
    root = Path.cwd()
    proj = root / ".project"

    if proj.exists():
        click.echo("Error: .project/ already exists", err=True)
        raise SystemExit(1)

    # Create directory structure
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "epics").mkdir()

    if hub:
        (proj / "projects").mkdir()
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


def _installed_skill_dirs() -> list:
    """Return .claude/ dirs that already contain the pm skills (global + cwd)."""
    candidates = [Path.home() / ".claude", Path.cwd() / ".claude"]
    return [c for c in candidates if (c / "skills" / "pm" / "SKILL.md").exists()]


@cli.command("refresh-skills")
def refresh_skills():
    """Rewrite the pm agent + skills wherever they are already installed.

    Checks ~/.claude and the current directory's .claude/ and re-renders the
    ProjectMan-managed files (agents/pm.md, skills/pm*) from the installed
    package's templates. Use setup-claude to install into a new location.
    """
    targets = _installed_skill_dirs()
    if not targets:
        click.echo(
            "No installed pm skills found in ~/.claude or ./.claude — "
            "run 'projectman setup-claude' (optionally --global) first."
        )
        return
    for target in targets:
        _write_claude_assets(target)
    click.echo(f"Refreshed pm skills in: {', '.join(str(t) for t in targets)}")


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
def repair():
    """Scan hub, discover projects, init missing PM data dirs, rebuild indexes and embeddings."""
    from projectman.hub.registry import repair as _repair
    report = _repair()
    click.echo(report)


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
            for name in config.projects:
                pm_dir = root / ".project" / "projects" / name
                if (pm_dir / "config.yaml").exists():
                    click.echo(f"\n--- Auditing {name} ---")
                    click.echo(run_audit(root, project_dir=pm_dir))
            return

    report = run_audit(root)
    click.echo(report)


@cli.group()
def changeset():
    """Manage cross-repo changesets."""
    pass


@changeset.command("create")
@click.argument("name")
@click.option("--projects", "-p", required=True, help="Comma-separated project names (e.g. api,web,worker)")
@click.option("--description", "-d", default="", help="Changeset description")
def changeset_create(name, projects, description):
    """Create a changeset grouping changes across repos."""
    from projectman.config import find_project_root
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)
    project_list = [p.strip() for p in projects.split(",") if p.strip()]
    if not project_list:
        click.echo("Error: at least one project is required", err=True)
        raise SystemExit(1)
    meta = store.create_changeset(name, project_list, description)
    click.echo(f"Created changeset {meta.id}: {meta.title}")
    for entry in meta.entries:
        click.echo(f"  - {entry.project}")


@changeset.command("add-project")
@click.argument("changeset_id")
@click.argument("project_name")
@click.option("--ref", default="", help="Git ref/branch for this project")
def changeset_add_project(changeset_id, project_name, ref):
    """Add a project to an existing changeset."""
    from projectman.config import find_project_root
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)
    meta = store.add_changeset_entry(changeset_id, project_name, ref=ref)
    click.echo(f"Added {project_name} to {meta.id} ({len(meta.entries)} projects)")


@changeset.command("status")
@click.argument("changeset_id", required=False)
def changeset_status(changeset_id):
    """Show changeset status (one by ID, or list all)."""
    from projectman.config import find_project_root
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)

    if changeset_id:
        meta, body = store.get_changeset(changeset_id)
        click.echo(f"{meta.id}: {meta.title} [{meta.status.value}]")
        for entry in meta.entries:
            click.echo(f"  {entry.project}: {entry.status} (ref: {entry.ref or 'none'})")
        if body:
            click.echo(f"\n{body}")
    else:
        changesets = store.list_changesets()
        if not changesets:
            click.echo("No changesets found.")
            return
        for cs in changesets:
            projects = ", ".join(e.project for e in cs.entries)
            click.echo(f"{cs.id}: {cs.title} [{cs.status.value}] — {projects}")


@changeset.command("create-prs")
@click.argument("changeset_id")
def changeset_create_prs(changeset_id):
    """Generate PR creation commands for a changeset."""
    from projectman.config import find_project_root
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)
    meta, body = store.get_changeset(changeset_id)

    if not meta.entries:
        click.echo("Error: changeset has no project entries", err=True)
        raise SystemExit(1)

    cross_refs = [f"- {e.project} (ref: {e.ref or 'TBD'})" for e in meta.entries]
    cross_ref_block = "\n".join(cross_refs)

    click.echo(f"PR commands for changeset {meta.id}: {meta.title}\n")
    for entry in meta.entries:
        if not entry.ref:
            click.echo(f"# {entry.project}: SKIPPED — no ref/branch set")
            continue
        pr_body = (
            f"## Part of changeset: {meta.title} ({meta.id})\n\n"
            f"### Cross-references\n{cross_ref_block}\n\n"
            f"{body or ''}"
        )
        click.echo(f"# {entry.project}:")
        click.echo(
            f'cd {entry.project} && '
            f'gh pr create --title "{meta.title}: {entry.project}" '
            f'--body "{pr_body}" '
            f'--head {entry.ref}'
        )
        click.echo()


@changeset.command("push")
@click.argument("changeset_id")
def changeset_push(changeset_id):
    """Check merge status and update hub refs when all PRs are merged."""
    from projectman.config import find_project_root
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)
    meta, body = store.get_changeset(changeset_id)

    merged = [e for e in meta.entries if e.status == "merged"]
    pending = [e for e in meta.entries if e.status != "merged"]

    if not pending:
        click.echo(f"All {len(merged)} PRs merged — safe to update hub submodule refs.")
        for e in meta.entries:
            click.echo(f"  {e.project}: merged")
    else:
        click.echo(f"NOT ready — {len(pending)} of {len(meta.entries)} still pending:")
        for e in pending:
            click.echo(f"  {e.project}: {e.status} (ref: {e.ref or 'none'})")
        if merged:
            click.echo(f"\nAlready merged ({len(merged)}):")
            for e in merged:
                click.echo(f"  {e.project}: merged")


@cli.command("changeset-status")
@click.argument("name", required=False)
def changeset_status_cmd(name):
    """Show changeset status dashboard — all active changesets or one by name."""
    from projectman.config import find_project_root
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)
    changesets = store.list_changesets()

    if name:
        matches = [cs for cs in changesets if cs.title == name or cs.id == name]
        if not matches:
            click.echo(f"No changeset found matching '{name}'")
            return
        changesets = matches

    if not changesets:
        click.echo("No changesets found.")
        return

    for cs in changesets:
        merged = [e for e in cs.entries if e.status == "merged"]
        not_merged = [e for e in cs.entries if e.status != "merged"]

        click.echo(f"{cs.id}: {cs.title} [{cs.status.value}] ({len(merged)}/{len(cs.entries)} merged)")
        for entry in cs.entries:
            flag = ""
            if entry.status == "merged" and not_merged:
                flag = " (hub ref blocked)"
            pr_info = f" PR #{entry.pr_number}" if entry.pr_number else ""
            click.echo(f"  {entry.project}: {entry.status}{pr_info}{flag}")
        click.echo()


@cli.command()
@click.option("--scope", default="all", help="Scope: hub, project:<name>, or all (default: all)")
@click.option("--message", "-m", default=None, help="Commit message (auto-generated if omitted)")
def commit(scope, message):
    """Commit .project/ changes with auto-generated message."""
    from projectman.config import find_project_root, load_config
    from projectman.store import Store

    root = find_project_root()
    config = load_config(root)

    if config.hub:
        from projectman.hub.registry import pm_commit
        try:
            result = pm_commit(scope=scope, message=message, root=root)
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
        click.echo(f"Message: {result['message']}")
        click.echo(f"Files ({len(result['files_committed'])}):")
        for f in result["files_committed"]:
            click.echo(f"  {f}")
    else:
        store = Store(root)
        try:
            result = store.commit_project_changes(message=message)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        click.echo(f"Committed: {result['commit_hash'][:8]}")
        click.echo(f"Message: {result['message']}")
        click.echo(f"Files ({len(result['files_changed'])}):")
        for f in result["files_changed"]:
            click.echo(f"  {f}")


@cli.command()
@click.option("--scope", default="hub", help="Scope: hub, project:<name>, or all (default: hub)")
@click.option("--dry-run", is_flag=True, help="Show what would be pushed without executing")
@click.option("--projects", default=None, help="Comma-separated project names to push (default: all dirty)")
def push(scope, dry_run, projects):
    """Push committed .project/ changes to remote."""
    from projectman.config import find_project_root, load_config
    from projectman.store import Store

    root = find_project_root()
    config = load_config(root)

    if config.hub:
        from projectman.hub.registry import pm_push, coordinated_push

        # --projects or --dry-run imply coordinated push
        if projects is not None or dry_run:
            project_list = (
                [p.strip() for p in projects.split(",") if p.strip()]
                if projects
                else None
            )
            result = coordinated_push(
                projects=project_list,
                dry_run=dry_run,
                root=root,
            )
            if "report" in result:
                click.echo(result["report"])
            if not dry_run and not result.get("pushed"):
                raise SystemExit(1)
        else:
            result = pm_push(scope=scope, root=root)
            if result.get("pushed"):
                click.echo(f"Pushed ({scope})")
                if "branch" in result:
                    click.echo(f"Branch: {result['branch']}")
                if "report" in result:
                    click.echo(result["report"])
            else:
                click.echo(f"Error: {result.get('error', 'push failed')}", err=True)
                raise SystemExit(1)
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


@cli.command("validate-branches")
def validate_branches_cmd():
    """Check that each submodule is on its expected tracked branch."""
    import os
    from projectman.hub.registry import validate_branches, format_branch_validation

    root = os.environ.get("PROJECTMAN_ROOT")
    root = Path(root) if root else None

    result = validate_branches(root=root)

    click.echo(format_branch_validation(result))
    raise SystemExit(0 if result["ok"] else 1)


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
