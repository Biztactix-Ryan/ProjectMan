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


def _init_attach(root: Path, name, prefix, description, branch: str = "projectman") -> None:
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
@click.option("--no-attach", "no_attach", is_flag=True, help="Scaffold a fresh store even when a projectman branch exists")
def init(name, prefix, description, no_attach):
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
    branch exists. In the attach case --prefix/--description/--name
    describe a store that is not being created, so they are ignored with a
    warning.
    """
    root = Path.cwd()
    proj = root / ".project"

    attach_root = None if no_attach else _attachable_root(root)
    if attach_root is not None:
        _init_attach(attach_root, name, prefix, description)
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

    ctx = dict(name=name, prefix=prefix, description=description)

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

    click.echo(f"Initialized project '{name}' in .project/")


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
    ("pm-decide", "skill_pm_decide.md.j2"),
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


PLUGIN_MARKETPLACE_SOURCE = "Biztactix-Ryan/ProjectMan"
PLUGIN_INSTALL_REF = "projectman@projectman"  # <plugin>@<marketplace>, per .claude-plugin/marketplace.json


def _plugin_deprecation_notice(command: str) -> None:
    """Print why COMMAND no longer installs anything and what to do instead.

    The plugin is the supported install (ADR-006); setup-claude and
    refresh-skills keep their old behaviour behind a hidden --legacy flag
    for one release.
    """
    click.echo(
        f"'projectman {command}' is deprecated: the ProjectMan Claude Code plugin is now the supported install.\n"
        "\n"
        "In Claude Code, run:\n"
        f"  /plugin marketplace add {PLUGIN_MARKETPLACE_SOURCE}\n"
        f"  /plugin install {PLUGIN_INSTALL_REF}\n"
        "\n"
        "Already installed with setup-claude? Run 'projectman migrate-to-plugin' "
        "(add --dry-run to preview) to remove the old agent, skills and MCP entries "
        "so the plugin takes over, then restart Claude Code.\n"
        "\n"
        'See docs/installation.md, "Install as a Claude Code plugin". Nothing was written.'
    )


@cli.command("setup-claude")
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="MCP transport mode (default: stdio)")
@click.option("--host", default="127.0.0.1", help="Host for SSE mode")
@click.option("--port", default=22001, type=int, help="Port for SSE mode")
@click.option("--global", "global_", is_flag=True, help="Install agent + skills to ~/.claude for all projects (registers MCP at user scope via the claude CLI)")
@click.option("--local-skills", is_flag=True, help="With --global: also write skill copies into the current project's .claude/")
@click.option("--legacy", is_flag=True, hidden=True, help="Run the pre-plugin install (removed next release)")
def setup_claude(transport, host, port, global_, local_skills, legacy):
    """Deprecated: install the ProjectMan Claude Code plugin instead.

    Prints the plugin install steps and points to migrate-to-plugin; writes
    nothing. The old behaviour (--legacy, hidden, one release): project-level
    install writes .mcp.json and .claude/ in the current directory; with
    --global installs to ~/.claude and registers the MCP server at user scope.
    """
    if not legacy:
        _plugin_deprecation_notice("setup-claude")
        return
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


def _frontmatter_name(path: Path):
    """Return the ``name:`` from a markdown file's YAML frontmatter, or None."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        meta = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return meta.get("name") if isinstance(meta, dict) else None


def _remove_claude_assets(claude_dir: Path, dry_run: bool = False) -> list[str]:
    """Remove the ProjectMan-managed agent + skills from a .claude/ directory.

    Ownership rule: a file is ProjectMan's only if it sits at a path this tool
    writes (agents/pm.md, skills/<CLAUDE_SKILLS|STALE_SKILLS>/SKILL.md) AND its
    frontmatter ``name:`` is the one the template gives it. Anything else —
    other skills, extra files inside a pm skill dir, a SKILL.md at a pm path
    with a different or missing name — is left alone and reported as kept. A
    managed file whose content differs from the current template (an older
    release, or a local edit) is still removed, with a note saying so.

    A skill dir is removed only once it is empty; empty agents/ and skills/
    parents are cleaned up. Prints one line per change ("would ..." with
    dry_run, which writes nothing) and returns those lines.
    """
    prefix = "would " if dry_run else ""
    lines: list[str] = []

    def say(line: str) -> None:
        lines.append(line)
        click.echo(line)

    def differs(path: Path, template_name: str) -> bool:
        try:
            return path.read_text() != _render_template(template_name)
        except (OSError, UnicodeDecodeError):
            return True

    removed: set[Path] = set()

    agent = claude_dir / "agents" / "pm.md"
    if agent.is_file():
        if _frontmatter_name(agent) == "pm":
            note = " (differs from the current template)" if differs(agent, "agent_pm.md.j2") else ""
            if not dry_run:
                agent.unlink()
            removed.add(agent)
            say(f"{prefix}remove {agent}{note}")
        else:
            say(f"keep {agent} (not written by ProjectMan: no 'name: pm' frontmatter)")

    skills = [(name, tmpl) for name, tmpl in CLAUDE_SKILLS] + [(name, None) for name in STALE_SKILLS]
    for skill_name, template_name in skills:
        skill_dir = claude_dir / "skills" / skill_name
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        label = "" if template_name else "stale "
        if skill_md.is_file():
            if _frontmatter_name(skill_md) == skill_name:
                note = ""
                if template_name and differs(skill_md, template_name):
                    note = " (differs from the current template)"
                if not dry_run:
                    skill_md.unlink()
                removed.add(skill_md)
            else:
                say(f"keep {skill_md} (not written by ProjectMan: no 'name: {skill_name}' frontmatter)")
                continue
        else:
            note = ""
        extras = sorted(p for p in skill_dir.iterdir() if p not in removed)
        if extras:
            if skill_md in removed:
                say(f"{prefix}remove {label}{skill_md}{note}")
            for extra in extras:
                say(f"keep {extra} (not written by ProjectMan)")
        else:
            if not dry_run:
                skill_dir.rmdir()
            say(f"{prefix}remove {label}{skill_dir}/{note}")

    if not dry_run:
        for parent in (claude_dir / "agents", claude_dir / "skills"):
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
    return lines


@cli.command("build-plugin")
@click.argument("plugin_root", default=".", type=click.Path(file_okay=False, path_type=Path))
def build_plugin(plugin_root):
    """Render the pm agent + skills into a Claude Code plugin root.

    Writes agents/pm.md and skills/<name>/SKILL.md under PLUGIN_ROOT (default:
    the current directory, which for this repo is the plugin root per ADR-006)
    from the same templates setup-claude uses. The output is committed; rerun
    after changing a template so the plugin does not drift from it.
    """
    if not (plugin_root / ".claude-plugin" / "plugin.json").exists():
        click.echo(f"Note: {plugin_root / '.claude-plugin' / 'plugin.json'} not found — writing anyway.")
    _write_claude_assets(plugin_root)
    click.echo(f"Built plugin skills and agent in {plugin_root}")


@cli.command("refresh-skills")
@click.option("--keep-local", is_flag=True, help="Keep project-local pm skill copies even when the same skills are installed globally in ~/.claude (they are pruned as duplicates by default)")
@click.option("--legacy", is_flag=True, hidden=True, help="Run the pre-plugin refresh (removed next release)")
def refresh_skills(keep_local, legacy):
    """Deprecated: the plugin updates its skills; see migrate-to-plugin.

    Prints the plugin install steps and points to migrate-to-plugin; writes
    nothing. The old behaviour (--legacy, hidden, one release) rewrites the
    pm agent + skills wherever they are already installed:

    Checks ~/.claude and the current directory's .claude/ and re-renders the
    ProjectMan-managed files (agents/pm.md, skills/pm*) from the installed
    package's templates. Use setup-claude to install into a new location.

    If the skills are installed both globally and in the current project,
    the local copies are superseded — Claude Code loads both and shows
    duplicates — so the local copies are removed (pass --keep-local to
    keep and refresh them instead).
    """
    if not legacy:
        _plugin_deprecation_notice("refresh-skills")
        return
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


def _is_setup_claude_mcp_entry(entry) -> bool:
    """True if a .mcp.json server entry has the shape setup-claude writes."""
    if not isinstance(entry, dict):
        return False
    if entry.get("type") == "sse":
        return set(entry) == {"type", "url"} and str(entry.get("url", "")).endswith("/sse")
    return (
        set(entry) <= {"command", "args", "type"}
        and entry.get("command") == "projectman"
        and entry.get("args") == ["serve"]
    )


#: Where /setup-project (ClaudeDefaultSetup) copies its session-start.sh in a
#: project, and the path every SessionStart command it wires points at.
PM_CONTEXT_HOOK = ".claude/hooks/pm-context.sh"


def _is_pm_context_script(path: Path) -> bool:
    """True if a pm-context.sh is ClaudeDefaultSetup's session-start.sh copy.

    The copy is recognised by the two things every version of that script
    carries: the ``## ProjectMan context`` heading it prints and the
    ``pm-context-`` per-session dedupe marker. Anything else is user-authored.
    """
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return False
    return "## ProjectMan context" in text and "pm-context-" in text


def _is_pm_context_hook(hook) -> bool:
    """True if a settings.json hook entry runs the per-project pm-context.sh."""
    return (
        isinstance(hook, dict)
        and hook.get("type", "command") == "command"
        and PM_CONTEXT_HOOK in str(hook.get("command", ""))
    )


def _remove_pm_context_hook(project_dir: Path, dry_run: bool, say) -> None:
    """Remove .claude/hooks/pm-context.sh and its SessionStart settings entry.

    Only what /setup-project wrote is touched: the script is removed only if
    it is recognisably the session-start.sh copy (see _is_pm_context_script);
    a user-modified script is kept, and so is its settings entry, so a hook
    the user still relies on keeps working. In .claude/settings.json only the
    SessionStart hook commands that run pm-context.sh are dropped — other
    hooks, matchers and settings keys are kept; a group, the SessionStart
    list and the hooks object are dropped once empty, and the file is deleted
    if nothing else was in it. Reports each change through ``say``.
    """
    prefix = "would " if dry_run else ""
    claude_dir = project_dir / ".claude"
    script = project_dir / PM_CONTEXT_HOOK

    if script.is_file():
        if not _is_pm_context_script(script):
            click.echo(
                f"keep {script} (not recognised as the ProjectMan session-start copy) "
                f"and its SessionStart entry in {claude_dir / 'settings.json'}"
            )
            return
        say(f"{prefix}remove {script}")
        if not dry_run:
            script.unlink()
            hooks_dir = script.parent
            if not any(hooks_dir.iterdir()):
                hooks_dir.rmdir()

    settings_path = claude_dir / "settings.json"
    if not settings_path.is_file():
        return
    try:
        raw = settings_path.read_text()
        settings = json.loads(raw)
    except (OSError, UnicodeDecodeError, ValueError):
        click.echo(f"keep {settings_path} (not valid JSON — remove the pm-context.sh SessionStart hook by hand)")
        return
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    groups = hooks.get("SessionStart") if isinstance(hooks, dict) else None
    if not isinstance(groups, list):
        return

    removed = 0
    kept_groups = []
    for group in groups:
        inner = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(inner, list):
            kept_groups.append(group)
            continue
        kept_inner = [h for h in inner if not _is_pm_context_hook(h)]
        removed += len(inner) - len(kept_inner)
        if len(kept_inner) == len(inner):
            kept_groups.append(group)
        elif kept_inner:
            kept_groups.append({**group, "hooks": kept_inner})
    if not removed:
        return

    if kept_groups:
        hooks["SessionStart"] = kept_groups
    else:
        del hooks["SessionStart"]
    if not hooks:
        del settings["hooks"]

    if not settings:
        say(f"{prefix}delete {settings_path} (it held only the pm-context.sh SessionStart hook)")
        if not dry_run:
            settings_path.unlink()
    else:
        say(f"{prefix}remove the pm-context.sh SessionStart hook from {settings_path} (keeping other settings)")
        if not dry_run:
            text = json.dumps(settings, indent=2)
            settings_path.write_text(text + "\n" if raw.endswith("\n") else text)


@cli.command("migrate-to-plugin")
@click.option("--dry-run", is_flag=True, help="List the changes without writing anything")
def migrate_to_plugin(dry_run):
    """Remove the setup-claude install so the ProjectMan plugin takes over.

    Removes the ProjectMan-managed agent + skills from ~/.claude and the
    current directory's .claude/, the user-scope projectman MCP server
    (via `claude mcp remove`), the projectman entry in ./.mcp.json, and the
    per-project .claude/hooks/pm-context.sh with its SessionStart entry in
    .claude/settings.json. Only files ProjectMan wrote are touched: other
    skills, extra files in a pm skill dir, other MCP servers, other hooks
    and settings, and a user-modified pm-context.sh are kept. The global
    ~/.claude/hooks/session-start.sh is left alone, with a note. Prints one
    line per change.
    """
    import subprocess

    prefix = "would " if dry_run else ""
    changes: list[str] = []

    def say(line: str) -> None:
        changes.append(line)
        click.echo(line)

    # 1. Skills + agent, in ~/.claude and ./.claude (once if they are the same dir).
    global_dir = Path.home() / ".claude"
    local_dir = Path.cwd() / ".claude"
    dirs = [global_dir]
    if local_dir.resolve() != global_dir.resolve():
        dirs.append(local_dir)
    for claude_dir in dirs:
        if claude_dir.is_dir():
            lines = _remove_claude_assets(claude_dir, dry_run=dry_run)
            changes.extend(line for line in lines if not line.startswith("keep "))

    # 2. User-scope MCP server, via the claude CLI.
    remove_cmd = ["claude", "mcp", "remove", "--scope", "user", "projectman"]
    if shutil.which("claude"):
        try:
            got = subprocess.run(
                ["claude", "mcp", "get", "projectman"],
                capture_output=True, text=True, timeout=60,
            )
            has_user_entry = got.returncode == 0 and "Scope: User" in got.stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            has_user_entry = False
            click.echo(f"claude mcp get failed ({exc}) — check with: claude mcp get projectman", err=True)
        if has_user_entry:
            say(f"{prefix}run {' '.join(remove_cmd)}")
            if not dry_run:
                result = subprocess.run(remove_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    click.echo(f"claude mcp remove failed: {result.stderr.strip()}", err=True)
                    click.echo(f"manual step: run {' '.join(remove_cmd)}")
    else:
        # No CLI to ask — look in ~/.claude.json, where user-scope servers live.
        has_user_entry = False
        claude_json = Path.home() / ".claude.json"
        try:
            data = json.loads(claude_json.read_text())
            has_user_entry = "projectman" in (data.get("mcpServers") or {})
        except (OSError, ValueError, AttributeError):
            pass
        if has_user_entry:
            say(f"manual step: claude CLI not found — run {' '.join(remove_cmd)}")

    # 3. The projectman entry in ./.mcp.json, keeping other servers.
    mcp_path = Path.cwd() / ".mcp.json"
    if mcp_path.is_file():
        try:
            config = json.loads(mcp_path.read_text())
        except ValueError:
            config = None
            click.echo(f"keep {mcp_path} (not valid JSON — remove the projectman entry by hand)")
        servers = config.get("mcpServers") if isinstance(config, dict) else None
        if isinstance(servers, dict) and "projectman" in servers:
            entry = servers.pop("projectman")
            if not servers and set(config) == {"mcpServers"} and _is_setup_claude_mcp_entry(entry):
                say(f"{prefix}delete {mcp_path} (it held only the projectman server)")
                if not dry_run:
                    mcp_path.unlink()
            else:
                kept = ", ".join(sorted(servers)) or "none"
                say(f"{prefix}remove projectman from {mcp_path} (keeping servers: {kept})")
                if not dry_run:
                    with open(mcp_path, "w") as f:
                        json.dump(config, f, indent=2)

    # 4. The per-project pm-context.sh hook /setup-project wired.
    _remove_pm_context_hook(Path.cwd(), dry_run, say)

    # 5. ClaudeDefaultSetup's global hook is not ours to remove — just say so.
    global_hook = global_dir / "hooks" / "session-start.sh"
    if global_hook.is_file():
        click.echo(
            f"note: {global_hook} (ClaudeDefaultSetup's global SessionStart hook) duplicates "
            "the plugin's SessionStart hook — left untouched; the two dedupe per session, "
            "remove it from ~/.claude/settings.json yourself if you no longer want it."
        )

    if not changes:
        click.echo("Nothing to migrate — no setup-claude install found.")
    elif dry_run:
        click.echo(f"Dry run: {len(changes)} change(s) listed, nothing written.")
    else:
        click.echo(f"Migrated: {len(changes)} change(s). Restart Claude Code to load the plugin instead.")


PROJECTMAN_REPO = "git+https://github.com/Biztactix-Ryan/ProjectMan"


@cli.command()
@click.option("--check", is_flag=True, help="Show the installed version and pipx source without upgrading")
@click.option("--no-skills", is_flag=True, help="Skip refreshing installed Claude skills after the upgrade")
def upgrade(check, no_skills):
    """Upgrade projectman via pipx (or check the installed version).

    After a successful upgrade, existing setup-claude skill copies (in
    ~/.claude and the current directory's .claude/) are re-rendered from the
    new version's templates (refresh-skills --legacy) so tools and skills stay
    in sync; none are created. Plugin installs update through /plugin.
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
        # setup-claude copies are deprecated (the plugin is the supported
        # install), but machines that still have them must not be left with
        # skills older than the tools. So: re-render existing copies via the
        # hidden --legacy path, never create new ones, and point at the
        # migration. This process still runs the pre-upgrade code, so the
        # refresh must be executed by the upgraded binary.
        home_claude = Path.home() / ".claude"
        local_claude = Path.cwd() / ".claude"
        has_copies = any(
            (d / "skills" / "pm" / "SKILL.md").exists() for d in (home_claude, local_claude)
        )
        if has_copies:
            exe = shutil.which("projectman")
            if exe:
                refresh = subprocess.run([exe, "refresh-skills", "--legacy"], text=True)
                if refresh.returncode != 0:
                    click.echo("Skill refresh failed — run 'projectman refresh-skills --legacy' manually.", err=True)
            else:
                click.echo("projectman executable not found on PATH — run 'projectman refresh-skills --legacy' manually to update skills.")
            click.echo(
                "These are setup-claude skill copies, which are deprecated: install the plugin "
                f"(/plugin install {PLUGIN_INSTALL_REF}) and run 'projectman migrate-to-plugin'."
            )


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


@cli.command()
def reindex():
    """Regenerate index.yaml and the four markdown indexes from the item files.

    One of the three rebuild points for the derived indexes (US-PM-29); the
    other two are the ``pm_reindex`` tool and ``projectman commit``, which
    rebuilds immediately before staging.
    """
    from projectman.config import find_project_root
    from projectman.indexer import write_index
    from projectman.store import Store

    root = find_project_root()
    store = Store(root)

    write_index(store)
    click.echo(f"Reindexed: {store.project_dir}")


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
def restore(filename):
    """Move a fixed file out of malformed/ back into stories/ or tasks/."""
    from projectman import server

    click.echo(_break_glass(server.pm_restore, filename=filename))


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
def fix_malformed(filename, id_, title, item_type, body, status, priority, points, story_id):
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
        )
    )


@cli.command("migrate-archived")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Write the changes. Without this flag the command only reports.",
)
def migrate_archived(apply_changes):
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
def audit():
    """Run project audit and generate DRIFT.md."""
    from projectman.config import find_project_root
    from projectman.audit import run_audit

    report = run_audit(find_project_root())
    click.echo(report)


@cli.command()
@click.option("--message", "-m", default=None, help="Commit message (auto-generated if omitted)")
def commit(message):
    """Commit .project/ changes with auto-generated message."""
    from projectman.config import find_project_root
    from projectman.indexer import write_index
    from projectman.store import Store

    store = Store(find_project_root())
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
def push():
    """Push committed .project/ changes to remote."""
    from projectman.config import find_project_root
    from projectman.store import Store

    store = Store(find_project_root())
    try:
        result = store.push_project_changes()
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Pushed {result['branch']} to {result['remote']}")


@cli.command("git-status")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON (for MCP/script consumption)")
def git_status_cmd(as_json):
    """Show git state of this project's PM store.

    The store is the branch that owns ``.project/`` — "projectman" for a
    worktree store (ADR-001), the checked-out branch otherwise.  Prints the
    same payload the ``pm_git_status`` MCP tool returns: branch, mount,
    upstream, ahead/behind and the uncommitted-file count.
    """
    from projectman.config import find_project_root
    from projectman.worktree import store_status_payload

    data = store_status_payload(find_project_root())

    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return

    store = data["pm_store"]
    click.echo(data["summary"])
    rows = [
        ("path", store.get("path") or ".project"),
        ("branch", store.get("branch") or ("detached HEAD" if store.get("detached") else "-")),
        ("mount", "worktree" if store.get("worktree") else "plain directory"),
        ("upstream", store.get("upstream") or "-"),
        ("ahead/behind", f"{store.get('ahead', 0)}/{store.get('behind', 0)}"),
        ("uncommitted", str(store.get("dirty_count", 0))),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        click.echo(f"  {label.ljust(width)}  {value}")


#: How long a printed status block suppresses a second one for the same
#: session.  Shared with ClaudeDefaultSetup's ``session-start.sh`` (and its
#: per-project copy ``pm-context.sh``): all three honour and touch the same
#: marker, so whichever hook runs first prints and the others stay quiet.
_SESSION_CONTEXT_DEDUPE_SECONDS = 30

#: Longest excerpt of the next-session note the status block carries.  The
#: block is a pointer, not the note: pm_context returns it in full.
_SESSION_CONTEXT_NOTE_CHARS = 200


def _session_context_marker(session_id: str) -> Path:
    """The per-session dedupe marker, at the path session-start.sh uses."""
    import os

    run_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / (
        f"claude-notify-{os.environ.get('USER') or 'u'}"
    )
    return run_dir / f"pm-context-{session_id}"


def _session_context_lines(root: Path) -> list[str]:
    """The status block for the store at ``root/.project``, one line per entry."""
    import collections

    from projectman.indexer import build_index
    from projectman.store import Store

    store = Store(root)
    index = build_index(store)
    config = store.config

    lines = [f"Project **{config.name}** ({config.prefix})"]

    by_type: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for entry in index.entries:
        status = "archived" if entry.archived else entry.status
        by_type[entry.type][status] += 1
    for item_type, plural in (("epic", "epics"), ("story", "stories"), ("task", "tasks")):
        counts = by_type[item_type]
        if counts:
            detail = ", ".join(
                f"{status} {count}"
                for status, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            )
            lines.append(f"- {plural}: {sum(counts.values())} ({detail})")

    if index.total_points:
        pct = round(index.completed_points * 100 / index.total_points)
        lines.append(f"- points: {index.completed_points}/{index.total_points} ({pct}%)")

    in_progress = [
        entry for entry in index.entries
        if entry.type == "task" and entry.status == "in-progress" and not entry.archived
    ]
    for entry in in_progress[:5]:
        lines.append(f"- in progress: {entry.id} {entry.title}")
    if len(in_progress) > 5:
        lines.append(f"- in progress: … and {len(in_progress) - 5} more (pm_active)")

    active_sprints = store.list_sprints(status="active")
    if active_sprints:
        sprint = active_sprints[0]
        lines.append(f"- active sprint: {sprint.id} {sprint.name}")

    note = store.read_next()
    if note:
        first = " ".join(note.split())
        if len(first) > _SESSION_CONTEXT_NOTE_CHARS:
            first = first[: _SESSION_CONTEXT_NOTE_CHARS].rstrip() + "…"
        lines.append(f"- next-session note (pm_next, {store.next_note_path}): {first}")

    handoff = store.project_dir / "HANDOFF.md"
    if handoff.exists():
        lines.append(f"- last handoff: {handoff} (read it before starting)")
    return lines


@cli.command("session-context")
def session_context():
    """Print the ProjectMan status block for a Claude Code SessionStart hook.

    Reads the hook's JSON on stdin (``cwd``, ``session_id``) and prints
    project counts, points, in-flight tasks, the active sprint and the
    next-session note when ``<cwd>/.project/config.yaml`` exists; anywhere
    else it prints nothing.  It dedupes with session-start.sh through the
    same per-session marker, and always exits 0 so a broken store never
    blocks a session from starting.
    """
    import sys
    import time

    payload = {}
    if not sys.stdin.isatty():
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    root = Path(payload.get("cwd") or Path.cwd())
    project_dir = root / ".project"
    if not (project_dir / "config.yaml").is_file():
        return

    marker = _session_context_marker(str(payload.get("session_id") or "nosession"))
    try:
        if time.time() - marker.stat().st_mtime < _SESSION_CONTEXT_DEDUPE_SECONDS:
            return  # already printed for this session moments ago
    except OSError:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass

    click.echo(f"## ProjectMan context ({project_dir})")
    try:
        for line in _session_context_lines(root):
            click.echo(line)
    except Exception as exc:  # the hook must never fail the session
        click.echo(f"ProjectMan project detected but the summary failed: {exc}")
    click.echo(
        "Use pm_context for full context, /projectman:pm-status for the dashboard, "
        "/projectman:pm board for what to pick up."
    )


def _thousands(value) -> str:
    """A token count with thousands separators, or ``-`` when unmeasured."""
    if value is None:
        return "-"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return f"{value:,.1f}"


@cli.command("orch-cost")
@click.argument("run_id")
@click.option(
    "--transcripts",
    "transcripts",
    default=None,
    type=click.Path(file_okay=False),
    help="Directory of session transcripts to search (default: ~/.claude/projects)",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON (for scripts)")
def orch_cost(run_id, transcripts, as_json):
    """Report what an orchestrator run cost in context.

    Finds the session transcript(s) mentioning RUN_ID and prints the growth
    that run put on the orchestrator's prompt: per dispatch and per accepted
    task, the API calls a dispatch costs, the bytes each tool returned, how
    long workers were waited on, and every full cache miss with the idle gap
    that caused it.
    """
    from projectman.orch_cost import analyze, find_transcripts

    matches = find_transcripts(run_id, root=transcripts)
    if not matches:
        root = transcripts or "~/.claude/projects"
        click.echo(
            f"No transcript under {root} contains run id {run_id}", err=True
        )
        raise SystemExit(1)

    reports = [dict(path=str(path), **analyze(path, run_id)) for path in matches]

    if as_json:
        payload = reports[0] if len(reports) == 1 else reports
        click.echo(json.dumps(payload, indent=2, default=str))
        return

    for index, report in enumerate(reports):
        if index:
            click.echo("")
        click.echo(report["path"])
        rows = [
            ("dispatches", str(report["dispatches"])),
            ("accepts", str(report["accepts"])),
            ("calls", str(report["calls"])),
            ("base", _thousands(report["base"])),
            ("peak", _thousands(report["peak"])),
            ("growth", _thousands(report["growth"])),
            ("growth per dispatch", _thousands(report["per_dispatch"])),
            ("growth per accepted task", _thousands(report["per_task"])),
            ("calls per dispatch", _thousands(report["calls_per_dispatch"])),
            ("output tokens per call", _thousands(report["output_per_call"])),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            click.echo(f"  {label.ljust(width)}  {value}")

        click.echo("")
        click.echo("  tool result bytes")
        tool_bytes = report["tool_bytes"]
        if tool_bytes:
            # analyze() already orders largest first; sort again so the
            # printed table is correct whatever a caller hands us.
            ordered = sorted(tool_bytes.items(), key=lambda item: (-item[1], item[0]))
            name_width = max(len(name) for name, _ in ordered)
            for name, size in ordered:
                click.echo(f"    {name.ljust(name_width)}  {size:,}")
        else:
            click.echo("    (none)")

        waits = report["waits"]
        click.echo("")
        click.echo(
            "  worker waits (minutes)  "
            f"p50 {_thousands(waits['p50'])}  "
            f"p90 {_thousands(waits['p90'])}  "
            f"max {_thousands(waits['max'])}  "
            f"(n={waits['n']})"
        )

        ttl = report["ttl"]
        click.echo("")
        click.echo(
            "  cache ttl (calls writing)  "
            f"5m {ttl['5m']}  1h {ttl['1h']}  "
            f"heartbeats {report['heartbeats']}"
        )

        click.echo("")
        click.echo("  full cache misses")
        if report["misses"]:
            for miss in report["misses"]:
                gap = miss["gap_min"]
                gap_text = "-" if gap is None else f"{gap:,.1f}"
                click.echo(
                    f"    {miss['at'] or '-'}  gap {gap_text} min  "
                    f"{_thousands(miss['tokens'])} tokens"
                )
        else:
            click.echo("    (none)")


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
