"""Move ``.project/`` onto a dedicated orphan branch mounted as a worktree.

This is the engine behind ``projectman migrate-worktree`` (US-PM-19).  The
migration automates the git incantation people otherwise run by hand:

1. create an empty orphan branch (a root commit "ProjectMan root" over the
   empty tree) — built with ``commit-tree``/``branch`` so the user's checkout
   is never touched;
2. untrack ``.project`` on the current branch (``git rm -r --cached``);
3. add a ``.project/`` entry to ``.gitignore`` and commit both changes;
4. move the PM files aside to a temp *stash* and mount the orphan branch at
   ``.project`` with ``git worktree add``;
5. restore the stashed files into the worktree and commit them there.

The stash is the safety net: it is never deleted until the worktree commit has
succeeded, and any failure after the move puts the files back where they were.

Snapshot import is the default and the only mode implemented here — the
history-preserving alternative is ``git filter-repo --subdirectory-filter
.project``, which callers are pointed at in the CLI help.  Both are recorded in
ADR-001 ("Store PM data on an orphan branch mounted as a worktree",
``.project/DECISIONS.md``): *"Migration is a snapshot import by default; ``git
filter-repo --subdirectory-filter .project`` is the history-preserving
variant."*

Remote handling (US-PM-19-9): when an ``origin`` remote is configured the new
branch is pushed with ``push -u`` twice — once right after the orphan branch is
created, and once after the import commit — so ``origin/<branch>`` ends at the
import commit and the local branch tracks it.  ADR-001 lists ``push -u when a
remote exists`` as part of the migration.  With no remote the pushes are
skipped with an informational message and the migration still succeeds, so a
remote-less repo migrates exactly as before.

The two pushes fail differently on purpose:

* the **first** push happens when branch creation is the only mutation made so
  far, so a failure is fatal — the branch is deleted and MigrationError carries
  git's stderr, leaving the repo as it was;
* the **second** push happens after the local migration has fully landed.
  Failing it must not undo completed, correct local work, so it is reported as
  a warning (``pushed`` False, ``push_error`` set) and the command still exits
  0.  The remedy is a plain ``git -C .project push``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_BRANCH = "projectman"
ROOT_COMMIT_MESSAGE = "ProjectMan root"
MAIN_COMMIT_MESSAGE = "Move .project onto the projectman worktree branch"
IMPORT_COMMIT_MESSAGE = "Import ProjectMan state"


class MigrationError(RuntimeError):
    """A migration precondition failed, or a git command did."""


def _git(
    *args: str,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command, raising MigrationError with git's own stderr."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise MigrationError(f"git {' '.join(args)} failed: {detail}")
    return proc


def _git_out(*args: str, cwd: Path) -> str:
    return _git(*args, cwd=cwd).stdout.strip()


def repo_root(start: Path) -> Path:
    """The top level of the git repo containing ``start``."""
    proc = _git("rev-parse", "--show-toplevel", cwd=start, check=False)
    if proc.returncode != 0:
        raise MigrationError(f"{start} is not inside a git repository")
    return Path(proc.stdout.strip()).resolve()


def branch_exists(root: Path, branch: str) -> bool:
    proc = _git(
        "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", cwd=root, check=False
    )
    return proc.returncode == 0


def remote_branch_exists(root: Path, branch: str, remote: str = "origin") -> bool:
    """True when a ``<remote>/<branch>`` ref is present in local ref storage.

    Only locally known refs are inspected — this never contacts the network, so
    a branch pushed by someone else since the last ``git fetch`` is invisible
    here.  That is deliberate: a migration must not block on network access.
    """
    proc = _git(
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/remotes/{remote}/{branch}",
        cwd=root,
        check=False,
    )
    return proc.returncode == 0


def has_remote(root: Path, remote: str = "origin") -> bool:
    """True when ``remote`` is configured for this repo.

    ``git remote get-url`` only reads ``.git/config`` — it never contacts the
    network, so this is safe to call before any mutation.
    """
    return _git("remote", "get-url", remote, cwd=root, check=False).returncode == 0


def is_worktree(path: Path) -> bool:
    """True when ``path`` is itself a git worktree (its ``.git`` is a file)."""
    return (path / ".git").is_file()


def worktree_branch(root: Path, path: Path) -> Optional[str]:
    """The branch checked out in the worktree at ``path``, or None.

    Parses ``git worktree list --porcelain`` record blocks rather than reading
    ``HEAD`` inside the directory, so a detached worktree (no ``branch`` line)
    is reported as None instead of the literal string "HEAD".  None is also
    what an unregistered path gets.
    """
    target = Path(path).resolve()
    record: dict[str, str] = {}
    lines = _git("worktree", "list", "--porcelain", cwd=root, check=False).stdout
    for line in [*lines.splitlines(), ""]:
        if not line.strip():
            entry = record.get("worktree")
            if entry and Path(entry).resolve() == target:
                ref = record.get("branch")
                return ref.rsplit("refs/heads/", 1)[-1] if ref else None
            record = {}
            continue
        key, _, value = line.partition(" ")
        record[key] = value
    return None


def upstream_of(root: Path, branch: str) -> Optional[str]:
    """``<remote>/<branch>`` configured as ``branch``'s upstream, or None."""
    proc = _git(
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        f"{branch}@{{upstream}}",
        cwd=root,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def current_branch(root: Path) -> str:
    return _git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=root)


def _tracked_under(root: Path, rel: str) -> bool:
    out = _git_out("ls-files", "--", rel, cwd=root)
    return bool(out)


def dirty_paths(root: Path, project_dir: str = ".project") -> list[str]:
    """The ``git status --porcelain`` entries that block a migration.

    What counts as dirty (and why):

    * **Blocks** — any staged or unstaged change to a *tracked* file anywhere in
      the repo (modification, deletion, rename, unmerged conflict).  The
      migration commits on the current branch, so anything already in the index
      would be swept into that commit; anything inside ``project_dir`` would
      additionally be carried, unreviewed, into the import commit on the orphan
      branch.
    * **Blocks** — *untracked* files under ``project_dir`` when the PM store is
      already partly tracked.  The import commit would silently pick them up.
    * **Does not block** — untracked files outside ``project_dir``: they are
      neither committed nor moved, so the migration cannot lose or mangle them.
    * **Does not block** — anything under ``project_dir`` when the store is
      untracked in its entirety.  That store is precisely what the migration
      exists to move onto its own branch; refusing there would make the command
      unusable for a ``.project/`` that was never committed.
    * **Does not block** — ignored files (git does not report them).

    Returns the offending ``"XY path"`` entries, in git's own order.
    """
    blocking: list[str] = []
    project_tracked = _tracked_under(root, project_dir)
    name = project_dir.strip("/")
    prefix = f"{name}/"

    # Not _git_out: its .strip() would eat the leading space of the first
    # status code (" M" -> "M"), shifting the whole line by one column.
    for line in _git("status", "--porcelain", cwd=root).stdout.splitlines():
        if not line.strip():
            continue
        code, path = line[:2], line[2:].strip()
        if " -> " in path:  # rename/copy: report the destination
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if code == "??":
            inside = path == name or path.startswith(prefix)
            if not (inside and project_tracked):
                continue
        blocking.append(f"{code} {path}")
    return blocking


def _has_staged_changes(root: Path) -> bool:
    return _git("diff", "--cached", "--quiet", cwd=root, check=False).returncode != 0


def _create_orphan_branch(root: Path, branch: str) -> str:
    """Create ``branch`` at a fresh empty root commit. Returns the commit sha.

    Uses plumbing (``hash-object`` + ``commit-tree`` + ``branch``) rather than
    ``checkout --orphan`` so the user's working tree and HEAD are untouched.
    """
    empty_tree = _git_out("hash-object", "-w", "-t", "tree", "--stdin", cwd=root)
    proc = subprocess.run(
        ["git", "commit-tree", empty_tree, "-m", ROOT_COMMIT_MESSAGE],
        cwd=str(root),
        capture_output=True,
        text=True,
        input="",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise MigrationError(f"git commit-tree failed: {detail}")
    sha = proc.stdout.strip()
    _git("branch", branch, sha, cwd=root)
    return sha


def ensure_gitignore_entry(root: Path, entry: str = ".project/") -> bool:
    """Append ``entry`` to .gitignore unless an equivalent line is present.

    Returns True when the file was written.
    """
    path = root / ".gitignore"
    existing = path.read_text() if path.exists() else ""
    wanted = entry.strip("/")
    for line in existing.splitlines():
        if line.strip().strip("/") == wanted:
            return False
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(f"{prefix}{entry}\n")
    return True


def migrate_to_worktree(
    start: Optional[Path] = None,
    branch: str = DEFAULT_BRANCH,
    project_dir: str = ".project",
    push: bool = True,
    remote: str = "origin",
) -> dict:
    """Move ``project_dir`` onto an orphan ``branch`` mounted as a worktree.

    Every precondition is checked *before* the first mutation, so a refusal
    leaves the repo byte for byte as it was: no branch created, no commit, an
    untouched .gitignore and an untouched ``project_dir``.

    Refuses when: ``project_dir`` is missing or already a worktree; ``branch``
    exists locally or as ``origin/<branch>`` (use ``projectman attach``); the
    working tree is dirty (see :func:`dirty_paths` for exactly what counts).

    When ``remote`` is configured and ``push`` is true, ``branch`` is pushed
    with ``push -u`` after it is created and again after the import commit.
    Only ``branch`` is ever pushed — the commit made on the current branch is
    left for the user to push themselves.  Pass ``push=False`` to migrate
    locally only.

    Returns a summary dict.  Raises MigrationError on any precondition or git
    failure; when the failure happens after the files were moved aside, they
    are restored before the error propagates.
    """
    root = repo_root(Path(start) if start else Path.cwd())
    target = root / project_dir

    # --- Preconditions.  Nothing below this block may mutate the repo. -------
    if not target.is_dir():
        raise MigrationError(f"{project_dir}/ does not exist at {root}")
    if is_worktree(target):
        raise MigrationError(
            f"{project_dir}/ is already a git worktree — nothing to migrate"
        )
    if branch_exists(root, branch):
        raise MigrationError(
            f"branch '{branch}' already exists — use `projectman attach` to mount it"
        )
    if remote_branch_exists(root, branch):
        raise MigrationError(
            f"branch '{branch}' already exists on origin — use `projectman attach` "
            "to mount it (this repo already knows origin/"
            f"{branch}; the migration would create a second, unrelated history)"
        )
    dirty = dirty_paths(root, project_dir)
    if dirty:
        listed = "\n".join(f"  {entry}" for entry in dirty[:10])
        more = f"\n  ... and {len(dirty) - 10} more" if len(dirty) > 10 else ""
        raise MigrationError(
            "working tree is dirty — commit or stash your changes first, then "
            f"re-run the migration:\n{listed}{more}"
        )
    # --- End of preconditions. -----------------------------------------------

    origin_branch = current_branch(root)
    # Read-only, and settled before the first mutation so the whole run agrees
    # on whether it is pushing.
    push_remote = remote if (push and has_remote(root, remote)) else None
    result: dict = {
        "root": str(root),
        "branch": branch,
        "original_branch": origin_branch,
        "untracked": False,
        "gitignore_updated": False,
        "main_commit": None,
        "worktree_commit": None,
        "stash": None,
        "remote": push_remote,
        "push_requested": push,
        "pushed": False,
        "push_error": None,
    }

    root_commit = _create_orphan_branch(root, branch)
    result["root_commit"] = root_commit

    if push_remote:
        # Branch creation is the only mutation so far, so a push failure here
        # is fatal and fully reversible: drop the branch and report git's own
        # error rather than migrating onto a branch that cannot reach origin.
        try:
            _git("push", "-u", push_remote, branch, cwd=root)
        except MigrationError as exc:
            _git("branch", "-D", branch, cwd=root, check=False)
            raise MigrationError(
                f"could not push branch '{branch}' to {push_remote} — nothing "
                f"was migrated (re-run with --no-push to migrate locally): {exc}"
            ) from exc

    # Untrack the PM files on the current branch and ignore the path there.
    if _tracked_under(root, project_dir):
        _git("rm", "-r", "--cached", "--quiet", project_dir, cwd=root)
        result["untracked"] = True
    result["gitignore_updated"] = ensure_gitignore_entry(root, f"{project_dir}/")
    _git("add", "--", ".gitignore", cwd=root)
    if _has_staged_changes(root):
        _git("commit", "-m", MAIN_COMMIT_MESSAGE, cwd=root)
        result["main_commit"] = _git_out("rev-parse", "HEAD", cwd=root)

    # Stash the files aside so `git worktree add` has a free path.  The stash
    # outlives every step below and is only removed once the worktree commit
    # has landed.
    stash_root = Path(tempfile.mkdtemp(prefix="projectman-migrate-"))
    stash = stash_root / Path(project_dir).name
    shutil.move(str(target), str(stash))
    result["stash"] = str(stash)

    try:
        _git("worktree", "add", project_dir, branch, cwd=root)
        shutil.copytree(stash, target, dirs_exist_ok=True)
        _git("add", "-A", cwd=target)
        _git("commit", "-m", IMPORT_COMMIT_MESSAGE, cwd=target)
        result["worktree_commit"] = _git_out("rev-parse", "HEAD", cwd=target)
    except Exception:  # noqa: BLE001 — re-raised after the files are restored
        # Put the files back exactly where they were; the caller can retry.
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        _git("worktree", "prune", cwd=root, check=False)
        shutil.move(str(stash), str(target))
        shutil.rmtree(stash_root, ignore_errors=True)
        result["stash"] = None
        # Drop the branch we created so a retry is not blocked by it. Only
        # ours: it still has to point at the root commit we just made, i.e.
        # nothing else has landed on it.
        if _git_out("rev-parse", branch, cwd=root) == root_commit:
            _git("branch", "-D", branch, cwd=root, check=False)
            if push_remote:
                # We pushed that same root commit a moment ago; leaving it on
                # the remote would make a retry refuse with "already exists on
                # origin". Best-effort — a failure here is not worth masking
                # the original error with.
                _git("push", push_remote, "--delete", branch, cwd=root, check=False)
                _git(
                    "update-ref", "-d", f"refs/remotes/{push_remote}/{branch}",
                    cwd=root, check=False,
                )
        raise

    if push_remote:
        # The local migration is complete and correct at this point. A failed
        # push must not undo it, so it downgrades to a warning: the user re-runs
        # `git -C .project push` once the remote is reachable again.
        proc = _git("push", "-u", push_remote, branch, cwd=target, check=False)
        if proc.returncode == 0:
            result["pushed"] = True
        else:
            result["push_error"] = (proc.stderr or proc.stdout or "").strip()

    shutil.rmtree(stash_root, ignore_errors=True)
    result["stash"] = None
    return result


def format_result(result: dict) -> str:
    """Human-readable summary of a completed migration."""
    branch = result["branch"]
    origin = result["original_branch"]
    rows = [
        ("orphan root commit", (result.get("root_commit") or "")[:8]),
        (
            f"{origin} commit",
            f"{result['main_commit'][:8]} (untracked .project, added .gitignore entry)"
            if result.get("main_commit")
            else "nothing to commit",
        ),
        (f"{branch} commit", (result.get("worktree_commit") or "")[:8]),
        ("push", _push_summary(result)),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [f"Migrated {result['root']}/.project onto branch '{branch}'"]
    lines += [f"  {label.ljust(width)} : {value}" for label, value in rows]
    lines += ["", f".project/ is now a worktree of the '{branch}' branch."]
    if result.get("push_error"):
        lines += [
            "",
            f"WARNING: push failed: {result['push_error']}",
            f"The local migration is complete — re-run `git -C .project push` "
            f"to publish '{branch}' once {result.get('remote') or 'the remote'} "
            "is reachable.",
        ]
    elif not result.get("remote"):
        if result.get("push_requested", True):
            note = (
                "no origin remote — skipped push; run "
                f"`git -C .project push -u origin {branch}` after adding one."
            )
        else:
            note = (
                "push skipped (--no-push); run "
                f"`git -C .project push -u origin {branch}` to publish it."
            )
        lines += ["", note]
    return "\n".join(lines)


def _push_summary(result: dict) -> str:
    """The `push` row of :func:`format_result`."""
    remote = result.get("remote")
    branch = result["branch"]
    if result.get("pushed"):
        return f"{remote}/{branch} (upstream set)"
    if result.get("push_error"):
        return f"FAILED — {remote}/{branch} is behind (see below)"
    if not result.get("push_requested", True):
        return "skipped (--no-push)"
    return "skipped (no origin remote)"


def attach_worktree(
    start: Optional[Path] = None,
    branch: str = DEFAULT_BRANCH,
    remote: str = "origin",
    project_dir: str = ".project",
) -> dict:
    """Mount an existing ``branch`` at ``project_dir`` with ``git worktree add``.

    This is the other half of :func:`migrate_to_worktree`: the migration
    *creates* the branch in the repo that owns the PM store, attach *mounts* a
    branch that already exists — the fresh-clone case, where ``origin/projectman``
    came down with the clone but ``.project/`` is empty or absent.

    The cases, in the order they are decided:

    * ``project_dir`` is already a worktree of ``branch`` — a friendly no-op
      (``already`` True), so running attach twice is safe;
    * ``project_dir`` is a worktree of some *other* branch (or a detached HEAD)
      — refused, naming what is actually mounted;
    * ``project_dir`` is a plain directory with content — refused without
      touching a single byte of it, because that is either an unmigrated store
      (which wants ``projectman migrate-worktree``) or someone's files;
    * ``branch`` exists locally — mounted as-is with ``git worktree add
      <project_dir> <branch>``; the existing branch is never recreated;
    * only ``<remote>/<branch>`` exists — mounted with ``git worktree add
      --track -b <branch> <project_dir> <remote>/<branch>``, which creates the
      local branch tracking the remote one;
    * neither exists — refused, pointing at ``git fetch`` or the migration.

    An empty ``project_dir`` is removed before the ``worktree add`` (git only
    reliably accepts a path that does not exist) and recreated if the add
    fails, so a refusal or a git error leaves the tree as it was found.

    Only local ref storage is inspected — attach never contacts the network, so
    a branch pushed since the last ``git fetch`` is invisible to it and the
    refusal says so.

    Returns a summary dict.  Raises :class:`MigrationError` on any refusal or
    git failure.
    """
    root = repo_root(Path(start) if start else Path.cwd())
    target = root / project_dir
    result: dict = {
        "root": str(root),
        "branch": branch,
        "project_dir": project_dir,
        "path": str(target),
        "attached": False,
        "already": False,
        "created_branch": False,
        "tracking": None,
        "head": None,
    }

    if target.exists() and not target.is_dir():
        raise MigrationError(
            f"{project_dir} exists and is not a directory — move it aside, then "
            "re-run `projectman attach`"
        )

    if is_worktree(target):
        mounted = worktree_branch(root, target)
        if mounted == branch:
            result["already"] = True
            result["attached"] = True
            result["tracking"] = upstream_of(root, branch)
            result["head"] = _git_out("rev-parse", "HEAD", cwd=target)
            return result
        where = f"branch '{mounted}'" if mounted else "a detached HEAD"
        raise MigrationError(
            f"{project_dir}/ is already a git worktree of {where}, not "
            f"'{branch}' — check it out there with `git -C {project_dir} "
            f"switch {branch}`, or remove that worktree before attaching"
        )

    local = branch_exists(root, branch)

    empty_dir = False
    if target.is_dir():
        if any(target.iterdir()):
            raise MigrationError(
                f"{project_dir}/ already exists and holds untracked content — "
                "refusing to overwrite it. If this is an unmigrated PM store, "
                "run `projectman migrate-worktree` to move it onto the "
                f"'{branch}' branch; otherwise move or remove {project_dir}/ "
                "yourself and re-run `projectman attach`."
            )
        empty_dir = True

    if not local and not remote_branch_exists(root, branch, remote):
        hint = (
            f"run `git fetch {remote}` first if it exists there"
            if has_remote(root, remote)
            else f"run `projectman migrate-worktree` to create it from {project_dir}/"
        )
        raise MigrationError(
            f"no branch '{branch}' locally or as {remote}/{branch} — nothing to "
            f"attach ({hint}). Attach never fetches: it reads local refs only."
        )

    if empty_dir:
        # `git worktree add` wants a path that does not exist; an empty
        # directory is ours to clear, and it goes back if the add fails.
        target.rmdir()

    if local:
        args = ["worktree", "add", project_dir, branch]
    else:
        args = [
            "worktree", "add", "--track", "-b", branch, project_dir,
            f"{remote}/{branch}",
        ]
    try:
        _git(*args, cwd=root)
    except MigrationError:
        if empty_dir and not target.exists():
            target.mkdir()
        raise

    result["attached"] = True
    result["created_branch"] = not local
    result["tracking"] = upstream_of(root, branch)
    result["head"] = _git_out("rev-parse", "HEAD", cwd=target)
    return result


def format_attach_result(result: dict) -> str:
    """Human-readable summary of a completed (or no-op) attach."""
    branch = result["branch"]
    project_dir = result.get("project_dir", ".project")
    tracking = result.get("tracking")
    if result.get("already"):
        lines = [
            f"Already attached: {project_dir}/ is a worktree of '{branch}' — "
            "nothing to do."
        ]
        if tracking:
            lines.append(f"  tracking : {tracking}")
        return "\n".join(lines)

    rows = [
        ("path", result.get("path", "")),
        (
            "branch",
            f"{branch} (created from {tracking})"
            if result.get("created_branch") and tracking
            else f"{branch} (created)"
            if result.get("created_branch")
            else f"{branch} (existing local branch)",
        ),
        ("tracking", tracking or "none — no upstream configured"),
        ("commit", (result.get("head") or "")[:8]),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [f"Attached {project_dir}/ to branch '{branch}'"]
    lines += [f"  {label.ljust(width)} : {value}" for label, value in rows]
    lines += ["", f"{project_dir}/ is now a worktree of the '{branch}' branch."]
    return "\n".join(lines)
