"""Move a hub's leftover subproject stores onto the submodules' own branches.

The engine behind ``projectman migrate-hub`` (US-PM-31-8).  Before US-PM-31 a
hub kept every subproject's PM data inside its *own* store, under a
``projects/{name}`` subdirectory of it, so every task edit in every project
landed as a commit on the hub repo.  The layout now is
``projects/{name}/.project`` — a git worktree of that submodule's
``projectman`` branch (see :mod:`projectman.hub.stores`).  This module carries
an existing hub across that line, once, for every project that still has data
in the old place.

Per project the move is:

1. attach or create the submodule's ``projectman`` branch and mount it at
   ``projects/{name}/.project`` — exactly what ``add-project`` does, via
   :func:`projectman.worktree.ensure_store_branch`;
2. copy the store across with :func:`shutil.copytree`, so every item file is
   byte-identical on the other side;
3. commit it on that branch with a message naming the hub path it came from;

and then, once, for the whole run: ``git rm -r`` the hub's copies and commit
that removal on the hub, then push each ``projectman`` branch that has a
remote.

Refusals happen *before the first mutation*.  The run is abandoned whole — not
half-migrated — when the hub tree or any affected submodule tree is dirty
(:func:`projectman.worktree.dirty_paths`, the same rule
``migrate-worktree`` uses), when a submodule is not checked out, or when the
submodule's ``projectman`` branch already carries a store of its own.  That
last one is a merge, and merging two PM stores is not a decision this command
is entitled to make: it says what it found and stops.

A hub with nothing left in the old place is not an error — it is the expected
state after the first successful run, so the command says so and exits 0.
``dry_run=True`` reports the same plan without touching anything.

The epics step (US-PM-36)
------------------------

Since US-PM-36 an epic lives in the hub's store only: a subproject story may
link to it, ``pm_epic`` rolls the link up across every store, and
``pm_create_epic`` in a hub writes nowhere else.  A hub built before that has
``epics/EPIC-{PROJECT}-N.md`` files scattered through the subproject stores,
so :func:`migrate_hub` has a second half that carries them up:

4. every subproject epic is moved into the hub's ``epics/`` under a fresh
   hub-prefixed ID handed out by the hub store's own counter, so
   ``config.next_epic_id`` advances exactly as ``pm_create_epic`` would have
   advanced it;
5. every story in *every* store — the hub's own included — whose ``epic_id``
   named one of those epics is rewritten to the new ID.  A story in one
   subproject that pointed at an epic living in another is rewritten too:
   the mapping is hub-wide, not per project;
6. each store that changed is committed inside itself, so a worktree store
   commits on its ``projectman`` branch, with a message naming the mapping.

The step runs after the store move so a freshly migrated store is included,
and it runs on a hub whose stores are *already* at ``projects/{name}/.project``
— that is the whole point of being able to run ``migrate-hub`` on its own
after US-PM-31 has been done.  It is bound by the same refusals: the hub tree
and every store it would commit in must be clean, checked before the first
mutation.  A hub with no subproject epics reports nothing to move, and
re-running is a no-op because there is nothing left outside the hub.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from .. import worktree
from ..config import load_config
from .stores import (
    PROJECTS_DIRNAME,
    STORE_DIRNAME,
    hub_store_dir,
    invalidate as invalidate_store_map,
    store_path,
    subproject_path,
)

#: Commit made on the hub once every store has been moved off it.
HUB_REMOVAL_MESSAGE = "Move subproject PM data onto the subprojects' own branches"

#: Commit made in every store the epics step touches, plus ": <mapping>".
EPICS_COMMIT_MESSAGE = "Move subproject epics up to the hub"

#: What the command prints when the old layout is already gone.
NOTHING_TO_MIGRATE = (
    "Nothing to migrate — no subproject PM data is left in the hub's own "
    "store. Each registered project keeps its stories, tasks and epics in "
    f"{PROJECTS_DIRNAME}/{{name}}/{STORE_DIRNAME} on its own "
    f"'{worktree.DEFAULT_BRANCH}' branch, and no subproject epic is left to "
    "move up to the hub."
)


def legacy_store_path(root: Path, name: str) -> Path:
    """Where *name*'s PM data lived before US-PM-31: ``.project/projects/{name}``.

    The one function under ``src/`` that still builds the retired hub-side
    store path, and the reason ``tests/test_hub_stores.py``'s source scan
    carries an allow-list for it.  A migration has to be able to find the
    thing it migrates; every *reader* goes through
    :func:`projectman.hub.stores.store_path` instead, which points at the new
    location.  Keep this the only such construction, so the old layout stays
    findable from exactly one place and dies with this command.
    """
    return hub_store_dir(root) / PROJECTS_DIRNAME / name


def import_message(source_rel: str) -> str:
    """The commit message used on the ``projectman`` branch, naming the source."""
    return f"{worktree.IMPORT_COMMIT_MESSAGE} from the hub's {source_rel}"


def _hub_index_root(root: Path) -> Path:
    """The directory whose git index tracks the hub's PM store.

    The hub repo itself normally, but a hub that has already run
    ``migrate-worktree`` keeps ``.project`` on its own branch as a worktree,
    and the removal has to be staged and committed *there*.
    """
    store = hub_store_dir(root)
    return store if worktree.is_worktree(store) else Path(root)


def _file_count(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file())


def _branch_files(sub: Path, branch: str, remote: str) -> Optional[list[str]]:
    """The paths the submodule's ``branch`` already tracks, or None if unborn.

    Reads the local branch when it exists and otherwise ``<remote>/<branch>``,
    which is what a fresh ``git submodule add`` clone has.  An orphan branch
    whose root commit is empty — the shape ``create_store_branch`` makes —
    comes back as ``[]``, which is a branch with no store on it and therefore
    safe to populate.
    """
    for ref in (branch, f"{remote}/{branch}"):
        if worktree._git(
            "rev-parse", "--verify", "--quiet", ref, cwd=sub, check=False
        ).returncode:
            continue
        listing = worktree._git_out("ls-tree", "-r", "--name-only", ref, cwd=sub)
        return [line for line in listing.splitlines() if line.strip()]
    return None


def _check_repo(path: Path, what: str) -> None:
    if worktree._git(
        "rev-parse", "--git-dir", cwd=path, check=False
    ).returncode:
        raise worktree.MigrationError(
            f"{what} at {path} is not a git repository — migrate-hub moves PM "
            "data onto a branch, so both the hub and every affected subproject "
            "must be git checkouts"
        )


def _hub_dirty(root: Path, registered: list[str]) -> list[str]:
    """The hub's blocking changes — :func:`worktree.dirty_paths`, less the
    submodules' *work tree* noise.

    A submodule whose checkout has uncommitted content shows up in the hub's
    own ``git status`` as an unstaged ``" M projects/{name}"``.  That is not
    something the hub's commit could sweep up (only staged paths are
    committed), and it is checked per subproject a few lines later with a
    message that says which repo and which file.  Reporting it here as "the
    hub is dirty" would be both wrong and unhelpful.  A *staged* pointer move
    (``"M  projects/{name}"``) still blocks: that one really would be
    committed alongside the removal.
    """
    subprojects = {f"{PROJECTS_DIRNAME}/{name}" for name in registered}
    return [
        entry
        for entry in worktree.dirty_paths(root, STORE_DIRNAME)
        if not (entry[:2] == " M" and entry[3:] in subprojects)
    ]


def _plan(
    root: Path,
    names: list[str],
    registered: list[str],
    branch: str,
    remote: str,
    push: bool,
) -> list[dict]:
    """Validate every project and describe what the run would do.

    Nothing here mutates the hub or any submodule: this whole function runs
    before the first ``git`` write, so a refusal leaves the tree byte for byte
    as it was found.
    """
    _check_repo(root, "the hub")

    # Missing checkouts first: a submodule that is not there at all also shows
    # in the hub's status, and "projects/x is not checked out" is the useful
    # half of that answer.
    for name in names:
        sub = subproject_path(root, name)
        rel_sub = f"{PROJECTS_DIRNAME}/{name}"
        if not sub.is_dir() or not (sub / ".git").exists():
            raise worktree.MigrationError(
                f"'{name}' still has PM data in the hub but {rel_sub} is not "
                "checked out — run `git submodule update --init "
                f"{rel_sub}` and re-run migrate-hub"
            )
        _check_repo(sub, f"subproject '{name}'")

    hub_dirty = _hub_dirty(root, registered)
    if hub_dirty:
        raise worktree.MigrationError(
            "the hub's working tree has uncommitted changes — commit or stash "
            "them first, so the migration's own commit is the only thing it "
            "makes:\n  " + "\n  ".join(hub_dirty)
        )

    plan: list[dict] = []
    for name in names:
        legacy = legacy_store_path(root, name)
        sub = subproject_path(root, name)
        target = store_path(root, name)
        rel_sub = f"{PROJECTS_DIRNAME}/{name}"

        sub_dirty = worktree.dirty_paths(sub, STORE_DIRNAME)
        if sub_dirty:
            raise worktree.MigrationError(
                f"subproject '{name}' has uncommitted changes in {rel_sub} — "
                "commit or stash them first:\n  " + "\n  ".join(sub_dirty)
            )

        if target.exists() and not worktree.is_worktree(target):
            if target.is_dir() and any(target.iterdir()):
                raise worktree.MigrationError(
                    f"{rel_sub}/{STORE_DIRNAME} already holds content but is "
                    "not a mounted worktree — move it aside and re-run "
                    "migrate-hub, which will not overwrite files it did not "
                    "put there"
                )

        existing = _branch_files(sub, branch, remote)
        if existing:
            raise worktree.MigrationError(
                f"subproject '{name}' already has a store on its '{branch}' "
                f"branch ({len(existing)} file(s), e.g. {existing[0]}) — "
                "migrate-hub will not merge two PM stores. Move the hub's copy "
                f"at {legacy.relative_to(root).as_posix()} in by hand, or "
                "delete whichever of the two is stale, then re-run."
            )

        plan.append(
            {
                "name": name,
                "branch": branch,
                "source": str(legacy),
                "source_rel": legacy.relative_to(root).as_posix(),
                "path": str(target),
                "path_rel": f"{rel_sub}/{STORE_DIRNAME}",
                "files": _file_count(legacy),
                "store_source": (
                    "attached" if existing is not None else "created"
                ),
                "commit": None,
                "hub_commit": None,
                "gitignore_updated": False,
                "remote": remote if worktree.has_remote(sub, remote) else None,
                "push_requested": push,
                "pushed": False,
                "push_error": None,
                "dry_run": False,
            }
        )
    return plan


# ─── The epics step (US-PM-36-8) ────────────────────────────────────────────


class MigrationResults(list):
    """The per-project store moves, with the hub-wide epics step attached.

    ``migrate_hub`` has two halves now, and only the first is per project.  A
    ``list`` of the store moves is still exactly what it always returned — so
    every caller, every ``results[0]["hub_commit"]`` and ``== []`` keeps
    working — and the second half rides along as attributes rather than as a
    fake entry that ``for entry in results`` would have to learn to skip.
    """

    def __init__(
        self,
        entries: object = (),
        *,
        epics: object = (),
        dry_run: bool = False,
    ) -> None:
        super().__init__(entries)  # type: ignore[arg-type]
        #: One dict per epic moved up — see :func:`_plan_epics`.
        self.epics: list[dict] = list(epics)  # type: ignore[arg-type]
        #: True when nothing was written; carried here because an epics-only
        #: dry run has no per-project entry to hang the flag on.
        self.dry_run = dry_run


def _frontmatter_block(text: str) -> Optional[tuple[list[str], int, int]]:
    """``(lines, start, end)`` of an item file's leading YAML block, or None.

    ``start``/``end`` bracket the keys, so ``lines[start:end]`` is the YAML
    and ``lines[end]`` is the closing ``---``.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines, 1, i
    return None


def read_field(text: str, field: str) -> Optional[str]:
    """The value of a top-level frontmatter key, unquoted, or None.

    Deliberately textual rather than a ``frontmatter.load`` + model parse: an
    epic that moves must arrive byte-identical apart from its ID, and a store
    old enough to need this migration is exactly the one likely to hold an
    item file the current models would refuse.  Only unindented keys match,
    so nothing nested is mistaken for the top-level one.
    """
    parsed = _frontmatter_block(text)
    if parsed is None:
        return None
    lines, start, end = parsed
    for line in lines[start:end]:
        if line.startswith(f"{field}:"):
            value = line[len(field) + 1 :].strip()
            return value.strip("'\"") or None
    return None


def set_field(text: str, field: str, value: str) -> Optional[str]:
    """*text* with one existing top-level frontmatter key set to *value*.

    Returns None when the file has no frontmatter or does not carry the key —
    a story with no ``epic_id`` is not one this migration should be inventing
    a link for.
    """
    parsed = _frontmatter_block(text)
    if parsed is None:
        return None
    lines, start, end = parsed
    for i in range(start, end):
        if lines[i].startswith(f"{field}:"):
            lines[i] = f"{field}: {value}"
            return "\n".join(lines)
    return None


def _epic_number(path: Path) -> tuple[int, str]:
    """Sort key that puts ``EPIC-P-2`` before ``EPIC-P-10``."""
    tail = path.stem.rsplit("-", 1)[-1]
    return (int(tail) if tail.isdigit() else 0, path.name)


def _epic_source(root: Path, name: str) -> Path:
    """The store to read *name*'s epics out of, old layout or new.

    The epics step runs after the store move, so in a combined run this is
    the freshly mounted store; planning happens *before* it, when the files
    are still in the hub's copy.  One function, so both phases enumerate the
    same epics.
    """
    legacy = legacy_store_path(root, name)
    return legacy if legacy.is_dir() else store_path(root, name)


def _is_git_repo(path: Path) -> bool:
    return not worktree._git(
        "rev-parse", "--git-dir", cwd=path, check=False
    ).returncode


def _store_status(store_dir: Path) -> list[str]:
    """``git status --porcelain`` entries inside a store, git's own order.

    Run *inside* the store, which is what makes it the right question for a
    worktree store: the answer is that branch's tree and nothing else.
    """
    return [
        line
        for line in worktree._git(
            "status", "--porcelain", cwd=store_dir
        ).stdout.splitlines()
        if line.strip()
    ]


def _plan_epics(
    root: Path,
    projects: list[str],
    hub_prefix: str,
    allocate: Callable[[], str],
) -> list[dict]:
    """Describe the epic moves, reading only.  ``allocate`` hands out hub IDs.

    Epics are walked in registration order and then by number, so the mapping
    is the same on a dry run as on the real one.  An epic that already carries
    the hub's prefix is left alone — the hub owns that ID space, and renaming
    it would break the very links this step exists to keep.  So is a file
    whose ``id`` is not epic-shaped: a malformed item is not something a
    migration should be renumbering.
    """
    from ..models import EPIC_ID

    hub_epics = hub_store_dir(root) / "epics"
    moves: list[dict] = []
    for name in projects:
        epics_dir = _epic_source(root, name) / "epics"
        if not epics_dir.is_dir():
            continue
        for path in sorted(epics_dir.glob("EPIC-*.md"), key=_epic_number):
            text = path.read_text()
            old_id = read_field(text, "id") or path.stem
            if not EPIC_ID.match(old_id):
                continue
            if old_id.startswith(f"EPIC-{hub_prefix}-"):
                continue
            new_id = allocate()
            moves.append(
                {
                    "project": name,
                    "old_id": old_id,
                    "new_id": new_id,
                    "source": str(path),
                    "target": str(hub_epics / f"{new_id}.md"),
                    "target_rel": f"{STORE_DIRNAME}/epics/{new_id}.md",
                    "stories": [],
                }
            )
    return moves


def _dry_run_allocator(hub_store) -> Callable[[], str]:
    """Hand out the IDs the hub store's counter *would* hand out.

    Same formula as :meth:`projectman.store.Store._next_epic_id` — the higher
    of the persisted counter and one past the highest epic on disk — but
    without writing ``config.yaml``, because a dry run changes nothing.
    """
    prefix = hub_store.config.prefix
    nxt = max(
        hub_store.config.next_epic_id,
        hub_store._highest_numbered(hub_store.epics_dir, f"EPIC-{prefix}-") + 1,
    )
    counter = [nxt]

    def allocate() -> str:
        eid = f"EPIC-{prefix}-{counter[0]}"
        counter[0] += 1
        return eid

    return allocate


def _epic_preconditions(root: Path, projects: list[str], skip: list[str]) -> None:
    """Refuse before the first mutation, for the stores the epics step writes.

    ``skip`` names the projects whose stores :func:`_plan` has already
    validated — in a combined run their data is still in the hub and the
    mounted store does not exist yet.  Everything else the step would commit
    in has to be clean for the same reason the store move does: the commit it
    makes must be the only thing it makes.
    """
    _check_repo(root, "the hub")

    hub_dirty = _hub_dirty(root, projects)
    if hub_dirty:
        raise worktree.MigrationError(
            "the hub's working tree has uncommitted changes — commit or stash "
            "them first, so the migration's own commit is the only thing it "
            "makes:\n  " + "\n  ".join(hub_dirty)
        )

    for name in projects:
        if name in skip:
            continue
        store = store_path(root, name)
        if not store.is_dir() or not _is_git_repo(store):
            continue
        dirty = _store_status(store)
        if dirty:
            raise worktree.MigrationError(
                f"subproject '{name}' has uncommitted changes in "
                f"{PROJECTS_DIRNAME}/{name}/{STORE_DIRNAME} — commit or stash "
                "them first, so the epic move's own commit is the only thing "
                "it makes:\n  " + "\n  ".join(dirty)
            )


def _commit_store(store_dir: Path, message: str) -> Optional[str]:
    """Stage and commit everything under *store_dir*, from inside it.

    The same shape ``hub.registry.pm_commit`` uses, and for the same reason:
    git run inside the store commits on the branch that owns it — the
    ``projectman`` branch of a worktree store, the checkout's branch for a
    plain directory.  Returns the new SHA, or None when nothing was staged.
    """
    worktree._git("add", "-A", "--", ".", cwd=store_dir)
    if worktree._git(
        "diff", "--cached", "--quiet", "--", ".", cwd=store_dir, check=False
    ).returncode:
        worktree._git("commit", "-m", message, cwd=store_dir)
        return worktree._git_out("rev-parse", "HEAD", cwd=store_dir)
    return None


def mapping_summary(moves: list[dict]) -> str:
    """``"EPIC-ALP-1 -> EPIC-HUB-1, EPIC-BET-1 -> EPIC-HUB-2"``."""
    return ", ".join(f"{m['old_id']} -> {m['new_id']}" for m in moves)


def _apply_epics(root: Path, projects: list[str], hub_store) -> list[dict]:
    """Move the epics up, relink every story, commit each store that changed.

    Returns the mapping, one dict per epic, with the stories it relinked.
    """
    from ..indexer import write_index
    from ..store import Store

    moves = _plan_epics(
        root, projects, hub_store.config.prefix, hub_store._next_epic_id
    )
    if not moves:
        return []

    hub_epics = hub_store_dir(root) / "epics"
    hub_epics.mkdir(parents=True, exist_ok=True)

    by_old: dict[str, dict] = {}
    touched: set[Path] = {hub_store_dir(root)}
    for move in moves:
        source = Path(move["source"])
        text = source.read_text()
        moved = set_field(text, "id", move["new_id"])
        Path(move["target"]).write_text(moved if moved is not None else text)
        source.unlink()
        touched.add(source.parent.parent)  # {store}/epics/EPIC-X.md
        by_old[move["old_id"]] = move

    # Relink every story in every store, the hub's own included: a story in
    # one subproject may well have linked to an epic that lived in another.
    for store_dir in [hub_store_dir(root)] + [
        store_path(root, name) for name in projects
    ]:
        stories_dir = store_dir / "stories"
        if not stories_dir.is_dir():
            continue
        for path in sorted(stories_dir.glob("*.md")):
            text = path.read_text()
            old = read_field(text, "epic_id")
            if old is None or old not in by_old:
                continue
            rewritten = set_field(text, "epic_id", by_old[old]["new_id"])
            if rewritten is None:
                continue
            path.write_text(rewritten)
            by_old[old]["stories"].append(read_field(text, "id") or path.stem)
            touched.add(store_dir)

    # The hub's derived indexes now describe epics that were not there when
    # they were last built — the same rebuild point pm_commit uses, and for
    # the same reason: what gets committed should match the items beside it.
    try:
        write_index(Store(root))
    except Exception:
        pass

    message = f"{EPICS_COMMIT_MESSAGE}: {mapping_summary(moves)}"
    for store_dir in sorted(touched):
        if not store_dir.is_dir() or not _is_git_repo(store_dir):
            continue
        _commit_store(store_dir, message)

    invalidate_store_map(root)
    return moves


def migrate_hub(
    root: Optional[Path] = None,
    *,
    branch: str = worktree.DEFAULT_BRANCH,
    remote: str = "origin",
    push: bool = True,
    dry_run: bool = False,
) -> list[dict]:
    """Move the leftover stores onto their branches, then the epics up to the hub.

    Returns a :class:`MigrationResults` — a list of one result dict per
    project whose store moved, in ``config.projects`` order, carrying the
    hub-wide epics mapping on ``.epics``.  An empty result with no epics
    means there was nothing left to migrate, which is a success, not an
    error.  Raises :class:`projectman.worktree.MigrationError` for every
    refusal, having mutated nothing.

    The two halves are independent: a hub whose stores already live at
    ``projects/{name}/.project`` gets only the epics step, and a hub with no
    subproject epics gets only the store move.

    With ``dry_run`` the same plan is returned with ``dry_run: True`` and no
    commits — every precondition is still checked, so a dry run is also the
    way to ask "would this work?".
    """
    from ..config import find_project_root

    root = Path(root) if root is not None else find_project_root()
    root = find_project_root(root)
    config = load_config(root)
    if not config.hub:
        raise worktree.MigrationError(
            "not a hub project — migrate-hub moves a hub's per-project PM "
            "data onto its submodules; run it from the hub repo"
        )

    from ..store import Store

    projects = list(config.projects)
    names = [
        name for name in projects if legacy_store_path(root, name).is_dir()
    ]

    # Read-only both halves first, so "there is nothing to do" stays the
    # cheapest, quietest answer it has always been: no repo check, no status
    # call, nothing to undo.
    hub_store = Store(root)
    planned_epics = _plan_epics(
        root, projects, hub_store.config.prefix, _dry_run_allocator(hub_store)
    )
    if not names and not planned_epics:
        return MigrationResults()

    plan = (
        _plan(root, names, projects, branch, remote, push) if names else []
    )
    if planned_epics:
        _epic_preconditions(root, projects, skip=names)

    if dry_run:
        for entry in plan:
            entry["dry_run"] = True
        return MigrationResults(plan, epics=planned_epics, dry_run=True)

    # --- Mutations start here. ----------------------------------------------
    for entry in plan:
        legacy = Path(entry["source"])
        sub = subproject_path(root, entry["name"])
        message = import_message(entry["source_rel"])

        def _populate(mounted: Path, _legacy: Path = legacy) -> None:
            shutil.copytree(_legacy, mounted, dirs_exist_ok=True)

        mount = worktree.ensure_store_branch(
            sub,
            branch=branch,
            project_dir=STORE_DIRNAME,
            remote=remote,
            populate=_populate,
            message=message,
        )
        entry["store_source"] = mount.get("source", entry["store_source"])
        entry["gitignore_updated"] = bool(mount.get("gitignore_updated"))

        target = Path(entry["path"])
        if mount.get("source") == "attached":
            # ``ensure_store_branch`` deliberately does not run ``populate``
            # when it attaches an existing branch.  The branch was proved
            # storeless in ``_plan``, so the copy is ours to make here.
            _populate(target)
            worktree._git("add", "-A", cwd=target)
            if worktree._git(
                "diff", "--cached", "--quiet", cwd=target, check=False
            ).returncode:
                worktree._git("commit", "-m", message, cwd=target)
                entry["commit"] = worktree._git_out("rev-parse", "HEAD", cwd=target)
        else:
            entry["commit"] = mount.get("commit")

    # --- Remove the hub's copies, in one commit. ----------------------------
    index_root = _hub_index_root(root)
    staged = False
    for entry in plan:
        legacy = Path(entry["source"])
        rel = legacy.relative_to(index_root).as_posix()
        if worktree._git_out("ls-files", "--", rel, cwd=index_root):
            worktree._git("rm", "-r", "-q", "--", rel, cwd=index_root)
            staged = True
        elif legacy.exists():
            # Never committed to the hub in the first place, so there is
            # nothing to stage — just take it away.
            shutil.rmtree(legacy)

    hub_commit = None
    if staged and worktree._git(
        "diff", "--cached", "--quiet", cwd=index_root, check=False
    ).returncode:
        moved = ", ".join(entry["name"] for entry in plan)
        worktree._git(
            "commit", "-m", f"{HUB_REMOVAL_MESSAGE}: {moved}", cwd=index_root
        )
        hub_commit = worktree._git_out("rev-parse", "HEAD", cwd=index_root)

    # The now-empty ``projects`` container under the hub store is part of the
    # retired layout too; git does not track directories, so remove it.
    if plan:
        container = Path(plan[0]["source"]).parent
        if container.is_dir() and not any(container.iterdir()):
            container.rmdir()

    # --- Carry the subproject epics up to the hub. --------------------------
    # After the store move, so a store that arrived a moment ago is included,
    # and reading the mounted stores rather than the plan, so a hub that was
    # already at the new layout gets exactly this half and nothing else.
    epics = _apply_epics(root, projects, hub_store)

    # --- Publish. -----------------------------------------------------------
    for entry in plan:
        entry["hub_commit"] = hub_commit
        if not push or not entry["remote"]:
            continue
        sub = subproject_path(root, entry["name"])
        proc = worktree.push_branch(sub, branch, entry["remote"], set_upstream=True)
        if proc.returncode == 0:
            entry["pushed"] = True
        else:
            entry["push_error"] = (proc.stderr or proc.stdout or "").strip()

    invalidate_store_map(root)
    return MigrationResults(plan, epics=epics)


def format_migration(results: list[dict]) -> str:
    """Human-readable summary, in the style of :func:`worktree.format_result`."""
    epics = list(getattr(results, "epics", []))
    if not results and not epics:
        return NOTHING_TO_MIGRATE

    dry = bool(results[0].get("dry_run")) if results else bool(
        getattr(results, "dry_run", False)
    )
    lines: list[str] = []
    if not results:
        lines += [
            "Every subproject store is already on its own branch — only the "
            "epics needed moving."
        ]
    verb = "Would migrate" if dry else "Migrated"
    count = len(results)
    if results:
        lines += [
            f"{verb} {count} subproject store{'' if count == 1 else 's'} out of "
            "the hub's own store."
        ]

    for entry in results:
        rows = [
            ("from", entry["source_rel"]),
            ("to", f"{entry['path_rel']} (worktree of '{entry['branch']}')"),
            (
                "branch",
                "attached (existing)"
                if entry["store_source"] == "attached"
                else "created (orphan)",
            ),
            (
                f"{entry['branch']} commit",
                (entry.get("commit") or "")[:8] or ("pending" if dry else "nothing to commit"),
            ),
            ("files", str(entry["files"])),
            ("push", "pending" if dry else worktree._push_summary(entry)),
        ]
        width = max(len(label) for label, _ in rows)
        lines += ["", f"{entry['name']}"]
        lines += [f"  {label.ljust(width)} : {value}" for label, value in rows]
        if entry.get("push_error"):
            lines += [
                f"  WARNING: push failed: {entry['push_error']}",
                f"  The local move is complete — re-run `git -C "
                f"{entry['path_rel']} push -u {entry.get('remote') or 'origin'} "
                f"{entry['branch']}` once the remote is reachable.",
            ]

    # --- The epics step: the old-to-new mapping, one line per epic. ---------
    lines += [""]
    if epics:
        moved = "Would move" if dry else "Moved"
        n = len(epics)
        lines += [
            f"{moved} {n} subproject epic{'' if n == 1 else 's'} up to the hub."
        ]
        width = max(len(m["old_id"]) for m in epics)
        for move in epics:
            relinked = move.get("stories") or []
            tail = (
                f" ({len(relinked)} "
                f"{'story' if len(relinked) == 1 else 'stories'} relinked: "
                f"{', '.join(relinked)})"
                if relinked
                else ""
            )
            lines += [
                f"  {move['project']}: {move['old_id'].ljust(width)} -> "
                f"{move['new_id']}{tail}"
            ]
        if dry:
            lines += [
                "  Every story linked to one of these gets its epic_id "
                "rewritten to the new ID."
            ]
    elif results:
        lines += ["No subproject epics to move — epics already live at hub level."]

    hub_commit = results[0].get("hub_commit") if results else None
    lines += [""]
    if dry:
        lines += [
            "Nothing was changed (--dry-run). Re-run without --dry-run to move "
            "the stores."
        ]
    else:
        if results:
            lines += [
                f"hub commit : {hub_commit[:8]} (removed the hub's copies)"
                if hub_commit
                else "hub commit : nothing to commit (the copies were untracked)"
            ]
            lines += [
                "",
                "Each subproject's PM data now lives in its own repository. "
                "Commit the submodule pointers when you next push the hub.",
            ]
        if epics:
            lines += [
                "",
                "The epics are committed in the hub store and in each "
                "subproject store they left; push those branches when you are "
                "ready.",
            ]
    return "\n".join(lines)
