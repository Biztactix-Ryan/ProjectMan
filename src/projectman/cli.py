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


@cli.command("setup-claude")
def setup_claude():
    """Install Claude Code integration (agent, skills, MCP config)."""
    root = Path.cwd()

    # Write .mcp.json
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

    # Write agent
    agents_dir = root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "pm.md").write_text(_render_template("agent_pm.md.j2"))
    click.echo("Wrote .claude/agents/pm.md")

    # Write skills (consolidated: /pm is the smart router, 3 power-user shortcuts)
    skills = [
        ("pm", "skill_pm.md.j2"),
        ("pm-status", "skill_pm_status.md.j2"),
        ("pm-plan", "skill_pm_plan.md.j2"),
        ("pm-do", "skill_pm_do.md.j2"),
        ("pm-autoscope", "skill_pm_autoscope.md.j2"),
    ]
    # Remove stale skills that were folded into /pm
    stale_skills = ["pm-scope", "pm-audit", "pm-fix", "pm-init"]
    for stale in stale_skills:
        stale_dir = root / ".claude" / "skills" / stale
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
            click.echo(f"Removed stale .claude/skills/{stale}/")

    for skill_name, template_name in skills:
        skill_dir = root / ".claude" / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(_render_template(template_name))
        click.echo(f"Wrote .claude/skills/{skill_name}/SKILL.md")

    click.echo("Claude Code integration installed. Restart Claude Code to activate.")


@cli.command()
def serve():
    """Start the MCP server."""
    try:
        from projectman.server import mcp
        mcp.run()
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
