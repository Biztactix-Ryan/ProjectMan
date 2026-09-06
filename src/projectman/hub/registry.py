"""Hub registry — manage subproject registration via git submodules."""

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .. import worktree
from ..config import load_config, save_config
from ..errors import NotFoundError, StoreError
from .stores import (
    NOT_ATTACHED,
    PROJECTS_DIRNAME,
    STORE_DIRNAME,
    hub_store,
    invalidate as invalidate_store_map,
    not_attached_row,
    projects_dir as _projects_dir,
    store_path,
    subproject_path,
)


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
        source: How the update happened (e.g. ``sync``, ``manual``).
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
            cwd=str(subproject_path(root, project_name)),
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

    projects_dir = _projects_dir(root)
    projects_dir.mkdir(exist_ok=True)

    target = projects_dir / name
    if target.exists():
        return f"error: project '{name}' already exists"

    # Add as git submodule
    try:
        cmd = ["git", "submodule", "add"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [git_url, f"{PROJECTS_DIRNAME}/{name}"]
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

    # Mount the subproject's PM store at projects/{name}/.project as a worktree
    # of the submodule's own `projectman` branch (US-PM-31).  The store belongs
    # to the subproject repo, not to the hub: when the clone brought
    # origin/projectman down with it that branch *is* the store and is simply
    # attached; otherwise the branch is created, mounted, scaffolded and
    # committed.  Nothing is ever written into the hub's own store — the
    # retired subproject subdirectory of it is gone for good (US-PM-31-6).
    repo = _parse_github_repo(git_url)
    deploy_branch = branch or "main"

    def _scaffold(path: Path) -> None:
        _init_subproject(path, name, repo=repo, deploy_branch=deploy_branch)

    try:
        mount = worktree.ensure_store_branch(
            target,
            branch=worktree.DEFAULT_BRANCH,
            project_dir=STORE_DIRNAME,
            populate=_scaffold,
        )
    except (worktree.MigrationError, OSError) as exc:
        # The store never mounted, so there is no store to register.  Leaving
        # the name out of config.projects is the honest outcome: a registered
        # project whose store does not exist would break every reader that
        # walks config.projects.  The submodule checkout is left in place —
        # removing it is a destructive guess — so the message says what to do
        # with it.
        invalidate_store_map(root)
        return (
            f"error: added the submodule at {PROJECTS_DIRNAME}/{name}, but could "
            f"not mount its PM store on the '{worktree.DEFAULT_BRANCH}' branch: "
            f"{exc}\n\n'{name}' was NOT registered in the hub. Fix the "
            f"subproject repo and re-run add-project after removing "
            f"{PROJECTS_DIRNAME}/{name} (git submodule deinit -f "
            f"{PROJECTS_DIRNAME}/{name} && git rm -f {PROJECTS_DIRNAME}/{name})."
        )

    # Register in config — only now that the store is actually there.
    if name not in config.projects:
        config.projects.append(name)
        save_config(config, root)
    invalidate_store_map(root)

    msg = f"added project '{name}' from {git_url}"
    if branch:
        msg += f" (branch: {branch})"
    rel = f"{PROJECTS_DIRNAME}/{name}/{STORE_DIRNAME}"
    if mount.get("source") == "attached":
        msg += (
            f"\n\nAttached the subproject's existing '{worktree.DEFAULT_BRANCH}' "
            f"branch as {rel} — its PM data came with the clone."
        )
    else:
        msg += (
            f"\n\nCreated the '{worktree.DEFAULT_BRANCH}' branch in "
            f"{PROJECTS_DIRNAME}/{name} and scaffolded a fresh store at {rel}. "
            f"Push it with: git -C {rel} push -u origin "
            f"{worktree.DEFAULT_BRANCH}"
        )
    msg += f"\n\nRun /pm-init {name} to set up project documentation."
    return msg


def _init_subproject(target: Path, name: str, repo: str = "", deploy_branch: Optional[str] = None) -> None:
    """Initialize PM data directory for a subproject.

    ``target`` is the store dir itself (e.g. hub_root/projects/{name}/.project/).
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

    # The five derived index files are rebuilt on demand, not tracked
    # (US-PM-29).  The hub's own .project/.gitignore already covers this
    # store through unanchored patterns, but a subproject added to a hub
    # scaffolded before that change has no such file above it, so give the
    # subproject its own.
    from ..indexer import write_store_gitignore

    write_store_gitignore(target)

    # A store that did not exist a moment ago now does — any cached map that
    # said otherwise is wrong.
    invalidate_store_map()


def set_branch(name: str, branch: str, root: Optional[Path] = None) -> str:
    """Change the branch a submodule tracks and update it."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"

    if name not in config.projects:
        return f"error: project '{name}' not registered in hub"

    target = subproject_path(root, name)
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


def _get_current_branch(name: str, root: Path) -> str:
    """Return the checked-out branch of a submodule, or ``""`` on error.

    This is the submodule's *code* checkout, not its PM store: the store lives
    on the ``projectman`` branch mounted at ``projects/{name}/.project`` and is
    read through :func:`projectman.worktree.store_git_state` instead.

    Returns ``"HEAD"`` when the submodule is in detached HEAD state.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(subproject_path(root, name)),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def _attach_missing_store(name: str, root: Path) -> Optional[tuple[bool, str]]:
    """Re-mount ``projects/{name}/.project`` if its worktree has gone missing.

    The one repair ``sync`` does, and the only write it makes inside a
    subproject.  A store worktree disappears the ordinary ways — a
    ``git worktree remove``, a fresh clone of the submodule, a pruned checkout
    — and until it is back every read of that project reports "not attached".

    Returns ``(succeeded, line)`` — a one-line report of what happened — or
    None when the store was already mounted and there was nothing to do.
    Never raises: a refusal (a copied store still sitting in the directory, no
    git repo, a git error) comes back as a ``(False, line)`` report, because
    one unfixable subproject must not abort the sync of the others.
    """
    checkout = subproject_path(root, name)
    store_dir = store_path(root, name)

    if worktree.is_worktree(store_dir):
        return None
    if not (checkout / ".git").exists():
        # Not a git checkout at all (a plain-directory fixture, or a submodule
        # that was never initialized) — there is no repo to mount a branch in.
        return None

    branch = worktree.DEFAULT_BRANCH
    try:
        if worktree.branch_exists(checkout, branch) or worktree.remote_branch_exists(
            checkout, branch
        ):
            worktree.attach_worktree(
                checkout, branch=branch, project_dir=STORE_DIRNAME
            )
            what = "attached"
        else:
            result = worktree.ensure_store_branch(
                checkout, branch=branch, project_dir=STORE_DIRNAME
            )
            what = result.get("source") or "created"
    except (worktree.MigrationError, OSError) as exc:
        return (False, f"  {name}: store not attached — {exc}")

    invalidate_store_map(root)
    rel = f"{PROJECTS_DIRNAME}/{name}/{STORE_DIRNAME}"
    if what == "attached":
        return (True, f"  {name}: re-attached store at {rel} ({branch})")
    return (True, f"  {name}: created and mounted the '{branch}' store at {rel}")


def sync(root: Optional[Path] = None) -> str:
    """Pull every submodule, then re-attach any store whose worktree is gone.

    The one hub-wide git verb left (US-PM-35).  Two passes, in this order:

    1. a fast-forward ``git pull`` in every checked-out submodule, skipping a
       dirty or diverged one with a note rather than touching it;
    2. a re-attach of every registered project whose ``.project`` worktree is
       missing, so a fresh clone or a removed worktree comes back mounted.

    The hub never commits or pushes on a subproject's behalf; what this
    returns is a report, and every line of it names the project it concerns.
    """
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    if not config.hub:
        return "error: not a hub project"

    projects_dir = _projects_dir(root)
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

    # Second pass: any store whose worktree is missing gets mounted again.
    store_lines: list[str] = []
    attached = 0
    for name in config.projects:
        report = _attach_missing_store(name, root)
        if report is None:
            continue
        succeeded, line = report
        attached += 1 if succeeded else 0
        store_lines.append(line)

    summary = (
        f"sync complete: {ok} updated, {skipped} skipped, {failed} failed, "
        f"{attached} stores attached"
    )
    parts = [summary, ""]
    parts.extend(results)
    if store_lines:
        parts.append("")
        parts.append("stores:")
        parts.extend(store_lines)
    return "\n".join(parts)


def list_projects(root: Optional[Path] = None) -> list[dict]:
    """List all registered projects with their status."""
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)

    results = []
    for name in config.projects:
        project_path = subproject_path(root, name)
        pm_dir = store_path(root, name)
        has_pm_data = (pm_dir / "config.yaml").exists()
        results.append({
            "name": name,
            "path": str(project_path),
            "exists": project_path.exists(),
            "initialized": has_pm_data,
        })

    return results


def _generate_hub_commit_message(changed_files: list[str]) -> str:
    """Generate a commit message from changed .project/ file paths.

    Parses story/task/epic IDs from filenames and produces messages like
    ``pm: update US-PRJ-5, US-PRJ-3-1`` or ``pm: update 3 stories, 2 tasks``.
    Falls back to count-based summaries when there are many changed items.

    The five derived index files are dropped before anything is counted:
    they render the items in the same commit, so naming them would turn a
    one-task edit into "1 task, config, 4 files" (US-PM-29).  New stores
    gitignore them; stores predating that migration still stage them.
    """
    from ..indexer import DERIVED_INDEX_FILES

    changed_files = [f for f in changed_files if Path(f).name not in DERIVED_INDEX_FILES]

    ids: list[str] = []
    config_changed = False
    other = 0

    # Paths are ".project/stories/X.md" for a plain store and "stories/X.md"
    # for a worktree-mounted one; the leading "/" makes both match the same
    # "/stories/" probe.
    for f in changed_files:
        name = Path(f).stem  # e.g. "US-PRJ-5" from ".project/stories/US-PRJ-5.md"
        probe = "/" + f
        if "/stories/" in probe:
            ids.append(name)
        elif "/tasks/" in probe:
            ids.append(name)
        elif "/epics/" in probe:
            ids.append(name)
        elif Path(f).name == "config.yaml":
            config_changed = True
        else:
            other += 1

    # If few enough IDs, list them explicitly
    if ids and len(ids) <= 4:
        return f"pm: update {', '.join(ids)}"

    # Otherwise, summarise by type counts
    stories = sum(1 for f in changed_files if "/stories/" in "/" + f)
    tasks = sum(1 for f in changed_files if "/tasks/" in "/" + f)
    epics = sum(1 for f in changed_files if "/epics/" in "/" + f)

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
    store_dir: Path,
    message: Optional[str] = None,
) -> dict:
    """Commit the PM changes of the one store at *store_dir*.

    US-PM-35 makes the hub a read-only rollup: there is no cross-project
    commit any more.  The caller (``server.pm_commit``, ``projectman
    commit``) resolves its optional ``prefix`` to exactly one store —
    the hub's own ``.project`` when no prefix is given, or
    ``projects/{name}/.project`` for the project that prefix names — and
    this commits that store and nothing else.

    Every git command runs *inside* ``store_dir``, so the commit lands on the
    branch that owns the store: the checkout's current branch for a plain
    directory, or the store's own ``projectman`` branch when it is a worktree
    (``projectman migrate-worktree``, and every subproject store under
    US-PM-31).  Run from the repo root a worktree path is ignored and ``git
    status`` reports nothing — which used to make every commit a silent
    ``nothing_to_commit``.

    Args:
        store_dir: The store to commit — ``{checkout}/.project``.
        message: Commit message.  Auto-generated from the staged filenames
            when ``None``.

    Returns:
        ``{"commit_hash", "message", "files_committed", "on_branch"}``, or
        ``{"nothing_to_commit": True}`` when the store is clean.  Committed
        paths are relative to the repository that owns the store:
        ``".project/..."`` for a plain directory, store-relative for a
        worktree.

    Raises:
        errors.NotFoundError: *store_dir* does not exist.
        errors.StoreError: the git add or commit failed.
    """
    store_dir = Path(store_dir)
    if not store_dir.is_dir():
        raise NotFoundError(f"{store_dir} does not exist")

    # Rebuild the derived indexes immediately before staging.  Mutating tools
    # no longer rewrite index.yaml and the four markdown indexes on every
    # write (US-PM-29), so this is one of the three declared rebuild points —
    # and it sits before the staging below, so a stale index is committed
    # matching the item files beside it.  A store that cannot be rebuilt (a
    # half-initialised one, say) is committed as it stands rather than
    # failing: a commit's job is to record what is on disk.
    from ..indexer import write_index
    from ..store import Store

    try:
        write_index(Store(store_dir.parent, project_dir=store_dir))
    except Exception:
        pass

    cwd = str(store_dir)

    # Stage everything under the store.  The pathspec is cwd-relative, so
    # nothing outside the store can be swept in.
    add = subprocess.run(
        ["git", "add", "-A", "--", "."], cwd=cwd, capture_output=True, text=True
    )
    if add.returncode != 0:
        raise StoreError(f"git add failed: {add.stderr.strip()}")

    diff = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--", "."],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        raise StoreError(f"git diff failed: {diff.stderr.strip()}")

    staged = [f for f in diff.stdout.strip().splitlines() if f]
    if not staged:
        return {"nothing_to_commit": True}

    commit_message = message or _generate_hub_commit_message(staged)

    commit = subprocess.run(
        ["git", "commit", "-m", commit_message],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        raise StoreError(f"git commit failed: {commit.stderr.strip()}")

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True
    )
    branch = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return {
        "commit_hash": sha.stdout.strip(),
        "message": commit_message,
        "files_committed": staged,
        "on_branch": branch.stdout.strip() if branch.returncode == 0 else None,
    }


def pm_push(store_dir: Path, remote: str = "origin") -> dict:
    """Push the branch that owns the one store at *store_dir*.

    The other half of US-PM-35's subtraction: no coordinated push, no rebase
    loop, no fan-out over subprojects.  The branch is read *inside* the store
    (:func:`projectman.worktree.store_git_state`), so a worktree store pushes
    its own ``projectman`` branch and a plain directory pushes the branch its
    checkout has out; the push itself runs from the checkout root, because a
    named-branch push does not depend on the worktree it is issued from and a
    relative remote URL must resolve from the same place every other push
    resolves it.

    Args:
        store_dir: The store to push — ``{checkout}/.project``.
        remote: Remote name, ``origin`` by default.

    Returns:
        ``{"pushed": True, "branch", "remote", "worktree", "store"}``.

    Raises:
        errors.NotFoundError (``not_found``): nothing is mounted at
            *store_dir*, so there is no branch to push.
        errors.StoreError (``store``): the store is on a detached HEAD, the
            remote is not configured, or git refused the push.
    """
    store_dir = Path(store_dir)
    if not store_dir.is_dir():
        raise NotFoundError(
            f"no store mounted at {store_dir} — nothing to push"
        )
    repo_root = store_dir.parent

    state = worktree.store_git_state(repo_root, store_dir.name)
    branch = state["branch"]
    if not branch:
        raise StoreError(
            f"Cannot push {store_dir} from a detached HEAD state — "
            f"checkout a branch first"
        )

    remotes_result = subprocess.run(
        ["git", "remote"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    remotes = [
        r.strip() for r in remotes_result.stdout.strip().splitlines() if r.strip()
    ]
    if remote not in remotes:
        raise StoreError(
            f"Remote '{remote}' not configured (available: "
            f"{', '.join(remotes) or 'none'})"
        )

    proc = worktree.push_branch(repo_root, branch, remote)
    if proc.returncode != 0:
        raise StoreError(
            f"Push failed: {(proc.stderr or proc.stdout or '').strip()}"
        )

    return {
        "pushed": True,
        "branch": branch,
        "remote": remote,
        "worktree": state["worktree"],
        "store": str(store_dir),
    }


# ─── git status dashboard ──────────────────────────────────────────


#: The empty ``last_commit`` — an unreadable log is not an error here.
_NO_COMMIT = {"sha": "", "date": "", "author": "", "message": ""}


def _last_commit(path: Path) -> dict:
    """Last commit of whatever git repository or worktree ``path`` is in.

    Called with a *store* directory, so what comes back is the last commit on
    that subproject's ``projectman`` branch — the last PM change, not the last
    code change.  Returns ``sha``, ``date``, ``author``, ``message``; all
    empty strings when the log cannot be read (no repo, unborn branch, no git).
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H|%ai|%an|%s"],
            cwd=str(path),
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
        return dict(_NO_COMMIT)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return dict(_NO_COMMIT)


def _unattached_status(name: str, root: Path, *, exists: bool) -> dict:
    """The status row for a subproject with no store mounted.

    Not an error and not an empty row: the hub knows the project, it just has
    nothing to read yet.  The wording comes from
    :func:`projectman.hub.stores.not_attached_row`, so the dashboard says the
    same thing about an unattached store as ``pm_status``, the rollup and
    ``GET /api/status`` (US-PM-31-9).
    """
    entry = hub_store(root, name) or {"name": name, "prefix": None}
    row = not_attached_row(entry)
    row.update(
        {
            "attached": False,
            "exists": exists,
            "branch": "",
            "checkout_branch": _get_current_branch(name, root) if exists else "",
            "worktree": False,
            "detached": False,
            "upstream": None,
            "dirty": False,
            "dirty_count": 0,
            "ahead": 0,
            "behind": 0,
            "last_commit": dict(_NO_COMMIT),
            "issues": ["Project directory missing"] if not exists else [row["hint"]],
        }
    )
    return row


def _collect_project_status(name: str, root: Path) -> dict:
    """The git status row for one subproject, read from its *store*.

    A hub is a read-only rollup of what each subproject's ``projectman``
    branch says (US-PM-35), so the branch this reports is the store's —
    ``projects/{name}/.project``, read through
    :func:`projectman.worktree.store_git_state`, which is the same helper
    ``pm_commit`` and ``pm_push`` consult to decide which branch they act on.
    The submodule's own checked-out branch rides along as
    ``checkout_branch``, because the code checkout is a separate fact from
    the PM data and conflating the two is what the old deploy-branch
    alignment scoring did.

    A subproject whose store is not mounted comes back as
    :func:`_unattached_status` — a row, with the attach hint, never a raise.

    Designed to be called in parallel via ThreadPoolExecutor.
    """
    checkout = subproject_path(root, name)
    if not checkout.exists():
        return _unattached_status(name, root, exists=False)

    entry = hub_store(root, name)
    if entry is None or not entry.get("attached"):
        return _unattached_status(name, root, exists=True)

    try:
        state = worktree.store_git_state(checkout, STORE_DIRNAME)
    except Exception:  # noqa: BLE001 — status must never fail the dashboard
        # Same degradation as the ``pm_store`` entry: an unreadable state is
        # the all-clean shape with no branch, never a raised dashboard.
        state = {
            "worktree": False, "branch": None, "detached": False,
            "upstream": None, "ahead": 0, "behind": 0,
            "dirty": False, "dirty_count": 0,
        }
    checkout_branch = _get_current_branch(name, root)
    last_commit = _last_commit(store_path(root, name))

    issues: list[str] = []
    if state["detached"]:
        issues.append("Store HEAD is detached")
    if state["dirty"]:
        n = state["dirty_count"]
        issues.append(f"Store has {n} uncommitted file{'s' if n != 1 else ''}")
    if state["behind"]:
        issues.append(f"Store is behind {state['upstream']} by {state['behind']} commits")

    return {
        "name": name,
        "prefix": entry.get("prefix"),
        "attached": True,
        "exists": True,
        "branch": state["branch"] or "",
        "checkout_branch": checkout_branch,
        "worktree": state["worktree"],
        "detached": state["detached"],
        "upstream": state["upstream"],
        "dirty": state["dirty"],
        "dirty_count": state["dirty_count"],
        "ahead": state["ahead"],
        "behind": state["behind"],
        "last_commit": last_commit,
        "issues": issues,
    }


def git_status_all(root: Optional[Path] = None) -> dict:
    """Collect git state for every registered submodule in a single call.

    Returns a dict with:

    - ``projects``: list of per-project status dicts, each describing that
      subproject's **store** (``projects/{name}/.project``), which is what a
      read-only rollup has to say about a repo it does not own:
      - ``name`` / ``prefix``: project name and its ID prefix
      - ``attached``: whether a store is mounted there at all
      - ``exists``: whether the subproject checkout exists
      - ``branch``: the branch owning the store (``projectman``), ``""`` when
        detached or unattached
      - ``checkout_branch``: the submodule's own checked-out code branch
      - ``worktree``: whether the store is a mounted worktree
      - ``detached``: whether the store's HEAD is off a branch
      - ``upstream``: the store branch's upstream, or None
      - ``dirty`` / ``dirty_count``: uncommitted changes under the store
      - ``ahead`` / ``behind``: store commits relative to ``upstream``
      - ``last_commit``: dict with ``sha``, ``date``, ``author``, ``message``
        — the store's last commit, i.e. the last PM change
      - ``issues``: list of human-readable problem strings
      An unattached subproject carries ``status`` and ``hint`` instead of
      real git state (see :func:`projectman.hub.stores.not_attached_row`).
    - ``total``: number of registered projects
    - ``issues``: count of projects with any problem (missing, unattached,
      detached, dirty or behind)
    - ``ok``: ``True`` if no projects have issues
    - ``summary``: human-readable summary string

    This is the single-command entry point for the hub git status dashboard.
    Git commands are run in parallel (one thread per project) for performance
    at 20+ repos.
    """
    from ..config import find_project_root
    root = root or find_project_root()
    config = load_config(root)
    pm_store = _pm_store_status(root)

    if not config.hub:
        return {
            "projects": [],
            "total": 0,
            "issues": 0,
            "ok": False,
            "summary": f"Not a hub project. PM store: {pm_store['description']}",
            "pm_store": pm_store,
        }

    names = list(config.projects)
    if not names:
        return {
            "projects": [],
            "total": 0,
            "issues": 0,
            "ok": True,
            "summary": f"No projects registered. PM store: {pm_store['description']}",
            "pm_store": pm_store,
        }

    # Collect status for all projects in parallel
    with ThreadPoolExecutor(max_workers=min(len(names), 16)) as pool:
        results = list(pool.map(lambda n: _collect_project_status(n, root), names))

    # Preserve registration order
    projects = results
    issue_count = sum(1 for p in projects if p["issues"])

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
        "summary": f"{summary} PM store: {pm_store['description']}",
        "pm_store": pm_store,
    }


def _pm_store_status(root: Path) -> dict:
    """The ``pm_store`` entry of :func:`git_status_all`.

    The PM store is reported separately from the submodules and from the
    hub's own branch because, once migrated, it lives on a worktree with its
    own branch, dirty state and ahead/behind counts (US-PM-21).  Keys mirror
    :func:`projectman.worktree.store_git_state` plus a one-line
    ``description``.  Never raises: an unreadable state degrades to the
    all-clean shape with ``branch`` None.
    """
    from ..worktree import describe_store_state, store_git_state

    try:
        state = store_git_state(root)
    except Exception:  # noqa: BLE001 — status must never fail the dashboard
        state = {
            "path": ".project", "worktree": False, "branch": None,
            "detached": False, "head": None, "upstream": None,
            "ahead": 0, "behind": 0, "dirty": False, "dirty_count": 0,
        }
    try:
        state["description"] = describe_store_state(state)
    except Exception:  # noqa: BLE001
        state["description"] = ".project"
    return state


def format_git_status(data: dict, *, verbose: bool = False) -> str:
    """Render ``git_status_all()`` output as a compact, scannable table.

    One row per subproject, in hub registration order — the order the hub
    lists its projects everywhere else.  The severity re-sort went with the
    deploy-branch alignment scoring it was built on (US-PM-35-8): the Issues
    column already says which rows need attention, and a stable order makes a
    20-project hub readable twice running.

    Args:
        data: dict returned by ``git_status_all()``.
        verbose: If True, include last commit info and dirty file details.

    Returns:
        Multi-line formatted string ready for terminal output.
    """
    projects = data.get("projects", [])
    total = data.get("total", 0)
    store = data.get("pm_store") or {}
    store_line = f"PM store: {store['description']}" if store.get("description") else ""

    if total == 0:
        return data.get("summary", "No projects.")

    # Registration order — see the docstring.
    listed = list(projects)

    # Column headers
    header = ["Project", "Store branch", "Checkout", "Dirty", "Ahead/Behind", "Issues"]

    # Build rows
    rows: list[list[str]] = []
    for p in listed:
        name = p["name"]
        if p.get("attached", True) is False:
            branch = NOT_ATTACHED
        elif p.get("detached"):
            branch = f"({p.get('branch') or 'detached'})"
        else:
            branch = p.get("branch", "")
        checkout = p.get("checkout_branch", "")
        dirty = f"{p['dirty_count']} mod" if p.get("dirty") else ""
        ahead = p.get("ahead", 0)
        behind = p.get("behind", 0)
        ab = f"{ahead}/{behind}" if (ahead or behind) else ""

        # Issues column: compact summary
        issues = p.get("issues", [])
        if issues:
            # Show first issue inline, rest in verbose
            issue_str = issues[0] if len(issues) == 1 else f"{len(issues)} issues"
        else:
            issue_str = ""

        rows.append([name, branch, checkout, dirty, ab, issue_str])

    # Calculate column widths
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # Format output
    lines: list[str] = []
    lines.append(f"Hub Git Status ({total} projects)")
    if store_line:
        lines.append(f"  {store_line}")
    lines.append("")

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
        for p in listed:
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
