"""The five index files are derived, not rewritten by every mutating tool.

Pins the acceptance criteria of story US-PM-29 ("A write leaves only the item
file and the activity log dirty"):

* US-PM-29-1 — after a ``pm_update`` on a clean tree, ``git status`` lists the
  item file and ``.project/activity.jsonl`` and nothing else.  Before the
  change, ``indexer.write_index`` ran after every mutating tool and re-rendered
  ``index.yaml`` plus the four markdown indexes whether or not their content
  had changed, so every single-field edit showed up as six modified files.
* US-PM-29-2 — the three surviving rebuild points still produce all five files
  from nothing: the ``pm_reindex`` tool, ``pm_commit`` (which rebuilds
  immediately before staging, so the commit carries an index that matches the
  item files it commits) and the ``projectman reindex`` CLI command.
* US-PM-29-5 — the readers.  With the per-write rebuilds gone the derived
  files can lag, so anything serving numbers out of them checks first;
  ``indexer.ensure_fresh`` and the web routes that call it are pinned in
  ``tests/test_index_freshness.py`` and ``tests/web/test_index_freshness.py``.
* US-PM-29-6 — the tracked-versus-generated call.  The five files are
  generated: a scaffolded store gitignores them, a commit carries the item
  file without its index echo, and the commit message counts neither.  The
  churn measurements behind the decision are in
  ``docs/reference/file-formats.md``.

Plus a source guard: neither ``server.py`` nor the web API may grow a new
per-write ``write_index`` call, which is exactly how the churn got in.
"""

import ast
import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from projectman.cli import cli
from projectman.indexer import write_index
from projectman.store import Store

SRC = Path(__file__).resolve().parents[1] / "src" / "projectman"
SERVER_PY = SRC / "server.py"
WEB_API_PY = SRC / "web" / "routes" / "api.py"

#: The derived files.  ``index.yaml`` feeds the readers; the four markdown
#: indexes are the human-facing render of the same data.
INDEX_FILES = (
    "index.yaml",
    "INDEX.md",
    "INDEX-EPICS.md",
    "INDEX-STORIES.md",
    "INDEX-TASKS.md",
)

#: The only functions in ``server.py`` allowed to rebuild the indexes.
REBUILD_POINTS = {"pm_reindex", "pm_commit"}

STORY_BODY = "As a developer I want the index files to stop churning on every write.\n"
TASK_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


# ─── Helpers ──────────────────────────────────────────────────────


def _git(args, cwd, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _dirty(root: Path) -> set[str]:
    """Every path git considers dirty, untracked files included.

    ``--untracked-files=all`` matters here: a rebuild that dropped a *new*
    file into ``.project/`` would be invisible to the default ``normal`` mode
    if the directory were otherwise unchanged.
    """
    out = _git(["status", "--porcelain", "--untracked-files=all"], root).stdout
    # Porcelain v1: two status columns, a space, then the path.
    return {line[3:].strip() for line in out.splitlines() if line.strip()}


def _index_paths(root: Path) -> list[Path]:
    return [root / ".project" / name for name in INDEX_FILES]


def _delete_indexes(root: Path) -> None:
    for path in _index_paths(root):
        assert path.exists(), f"fixture should have seeded {path.name}"
        path.unlink()


def _missing_indexes(root: Path) -> list[str]:
    return [p.name for p in _index_paths(root) if not p.exists()]


def _reset_caches() -> None:
    """Drop both caches so the next read comes off disk."""
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


def _seed_story_and_task(root: Path) -> tuple[str, str]:
    """Create a story and a task through the Store, inside the fixture repo."""
    store = Store(root)
    story, _ = store.create_story("Indexes are derived", STORY_BODY)
    task = store.create_task(story.id, "A task to update", TASK_BODY)
    return story.id, task.id


def _commit_everything(root: Path, message: str) -> None:
    """Rebuild the indexes, stage the whole tree and commit, leaving it clean."""
    write_index(Store(root))
    _git(["add", "-A"], root)
    _git(["commit", "-m", message], root)
    assert _dirty(root) == set(), "fixture failed to reach a clean tree"


def _on_disk_index(root: Path) -> dict:
    """``.project/index.yaml`` as it exists in the worktree.

    Since US-PM-29-6 the derived files are gitignored, so there is no
    ``HEAD:`` copy to read: the worktree is the only place they live, and
    keeping *it* in step with the items a commit carries is what makes
    ``pm_commit`` a rebuild point.
    """
    return yaml.safe_load((root / ".project" / "index.yaml").read_text())


def _tracked(root: Path) -> list[str]:
    return _git(["ls-tree", "-r", "--name-only", "HEAD"], root).stdout.split()


def _entry(index: dict, item_id: str) -> dict:
    for entry in index["entries"]:
        if entry["id"] == item_id:
            return entry
    raise AssertionError(f"{item_id} missing from index entries")


@pytest.fixture
def project(tmp_git_project, monkeypatch):
    """A committed git project, cwd'd into, with a story and a task.

    The seeding commit happens *after* the items are created, so the tree the
    assertions start from is clean and every index file is tracked at its
    current content — the state a real store is in between writes.
    """
    monkeypatch.chdir(tmp_git_project)
    _reset_caches()
    story_id, task_id = _seed_story_and_task(tmp_git_project)
    _commit_everything(tmp_git_project, "seed story and task")
    _reset_caches()
    return tmp_git_project, story_id, task_id


# ─── US-PM-29-1: a write dirties two files ────────────────────────


def test_pm_update_dirties_only_the_item_file_and_the_activity_log(project):
    """The story's headline criterion, asserted as an exact set."""
    root, _story_id, task_id = project
    from projectman.server import pm_update

    pm_update(task_id, status="in-progress")

    assert _dirty(root) == {
        f".project/tasks/{task_id}.md",
        ".project/activity.jsonl",
    }


def test_pm_update_leaves_every_index_file_untouched(project):
    """The same criterion from the other side: no index file is rewritten.

    Asserted separately on mtime as well as content, because ``write_index``
    is unconditional — it would rewrite a byte-identical file, and only the
    timestamp would show it.
    """
    root, _story_id, task_id = project
    from projectman.server import pm_update

    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in _index_paths(root)}

    pm_update(task_id, status="in-progress")

    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in _index_paths(root)}
    assert after == before


def test_a_second_write_still_dirties_only_two_files(project):
    """Repeated writes do not accumulate dirty index files."""
    root, story_id, task_id = project
    from projectman.server import pm_update

    pm_update(task_id, status="in-progress")
    pm_update(story_id, status="active")

    assert _dirty(root) == {
        f".project/tasks/{task_id}.md",
        f".project/stories/{story_id}.md",
        ".project/activity.jsonl",
    }


# ─── US-PM-29-2: the three rebuild points ─────────────────────────


def test_pm_reindex_regenerates_all_five_index_files(project):
    root, _story_id, _task_id = project
    from projectman.server import pm_reindex

    _delete_indexes(root)
    assert _missing_indexes(root) == list(INDEX_FILES)

    pm_reindex()

    assert _missing_indexes(root) == []


def test_cli_reindex_regenerates_all_five_index_files(project):
    root, _story_id, _task_id = project

    _delete_indexes(root)
    assert _missing_indexes(root) == list(INDEX_FILES)

    result = CliRunner().invoke(cli, ["reindex"])

    assert result.exit_code == 0, result.output
    assert _missing_indexes(root) == []


def test_pm_commit_regenerates_all_five_index_files(project):
    root, _story_id, task_id = project
    from projectman.server import pm_commit, pm_update

    pm_update(task_id, status="in-progress")
    _delete_indexes(root)

    pm_commit()

    assert _missing_indexes(root) == []


def test_pm_commit_leaves_an_index_that_matches_the_items_it_committed(project):
    """The rebuild sits before staging, so the index matches what was committed.

    This is the reason ``pm_commit`` is a rebuild point at all: with the
    per-write calls gone, ``index.yaml`` would otherwise lag the item files
    that were just committed, and the next reader would serve the old status.
    """
    root, _story_id, task_id = project
    from projectman.server import pm_commit, pm_update

    assert _entry(_on_disk_index(root), task_id)["status"] == "todo"

    pm_update(task_id, status="in-progress")
    _delete_indexes(root)

    pm_commit()

    assert _entry(_on_disk_index(root), task_id)["status"] == "in-progress"


# ─── US-PM-29-6: derived, therefore untracked ─────────────────────


def test_the_commit_carries_the_item_file_and_not_its_index_echo(project):
    """The decision recorded in ``docs/reference/file-formats.md``.

    The five files render the items committed beside them, so committing
    both puts the same change in the commit twice — and ``index.yaml`` in
    particular is a guaranteed conflict for any two branches that touched
    different tasks.  A scaffolded store gitignores them.
    """
    root, _story_id, task_id = project
    from projectman.server import pm_commit, pm_update

    pm_update(task_id, status="in-progress")
    pm_commit()

    tracked = _tracked(root)
    assert f".project/tasks/{task_id}.md" in tracked
    for name in INDEX_FILES:
        assert f".project/{name}" not in tracked


def test_a_scaffolded_store_gitignores_the_derived_files(tmp_path, monkeypatch):
    """``projectman init`` writes the ignore rules, so no migration is needed."""
    from projectman.indexer import DERIVED_INDEX_FILES

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["init", "--name", "scaffolded"])
    assert result.exit_code == 0, result.output

    ignored = (tmp_path / ".project" / ".gitignore").read_text().splitlines()
    for name in DERIVED_INDEX_FILES:
        assert name in ignored


def test_the_commit_message_does_not_count_the_derived_files(project):
    """A one-task edit reads as one task, whatever the indexes did.

    Stores scaffolded before the migration still track and stage the five
    files; the message generator drops them either way, so the same edit
    reads the same in an old store and a new one.
    """
    root, _story_id, task_id = project
    store = Store(root)

    changed = [f".project/tasks/{task_id}.md"] + [f".project/{n}" for n in INDEX_FILES]

    assert store._generate_commit_message(changed) == "pm: update 1 task"


def test_the_tree_is_clean_after_pm_commit(project):
    """The regenerated indexes are staged, not left dirty behind the commit."""
    root, _story_id, task_id = project
    from projectman.server import pm_commit, pm_update

    pm_update(task_id, status="in-progress")
    _delete_indexes(root)

    pm_commit()

    assert _dirty(root) == set()


# ─── Source guard: no new per-write rebuild ───────────────────────


def _is_write_index(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "write_index"
    if isinstance(func, ast.Attribute):
        return func.attr == "write_index"
    return False


def _write_index_callers(tree: ast.AST) -> set[str]:
    """Names of the top-level functions in *tree* that call ``write_index``.

    A call inside a nested helper is attributed to the outermost enclosing
    function, which is the unit the rule is about; a call at module scope is
    reported as ``<module>``.
    """
    callers: set[str] = set()

    def visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, owner if owner is not None else child.name)
                continue
            if isinstance(child, ast.Call) and _is_write_index(child.func):
                callers.add(owner if owner is not None else "<module>")
            visit(child, owner)

    visit(tree, None)
    return callers


def test_server_rebuilds_indexes_only_in_pm_reindex_and_pm_commit():
    """A regression guard on the shape of the fix, not just its effect.

    ``write_index`` used to be called from 19 sites in ``server.py`` — once
    after every mutating tool.  Any new one would silently restore the churn
    these tests pin, and would be easy to add while following the surrounding
    code, so the source is asserted directly.
    """
    callers = _write_index_callers(ast.parse(SERVER_PY.read_text()))

    assert callers - REBUILD_POINTS == set(), (
        "write_index must only be called from pm_reindex and pm_commit; "
        f"also called from: {sorted(callers - REBUILD_POINTS)}"
    )
    # Not vacuous: both rebuild points must still be there.
    assert callers == REBUILD_POINTS


def test_the_web_api_never_rebuilds_the_indexes_on_a_write():
    """The same rule, on the other write surface.

    ``web/routes/api.py`` had ten ``write_index`` calls — one after every
    create, update, archive and grab — so a dashboard write churned the same
    five files an MCP write used to.  The web app has no rebuild point of its
    own: its read routes call ``indexer.ensure_fresh`` instead, so nothing in
    this module should rebuild at all.
    """
    callers = _write_index_callers(ast.parse(WEB_API_PY.read_text()))

    assert callers == set(), (
        "the web API must not rebuild the indexes; called from: "
        f"{sorted(callers)}"
    )
    # Not vacuous: the freshness check has to be there instead.
    assert "ensure_fresh" in WEB_API_PY.read_text()
