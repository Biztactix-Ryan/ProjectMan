"""The kept git operations still behave as before the changeset/PR subtraction.

Verifies the acceptance criterion for story US-PM-27 (task US-PM-27-3):

    > pm_commit and pm_push and pm_git_status behave as before on this repo
    > and their tests pass

Changesets and the pull-request workflow were removed from
``src/projectman`` (US-PM-27-6/7/8), and hub mode after them (EPIC-PM-6).
The commit, push and status paths were meant to survive both subtractions
untouched, so this file drives them end to end against throwaway git repos
under ``tmp_path``:

1. ``Store.commit_project_changes`` lands a real commit carrying the
   ``.project/`` store files, with the auto-generated message shapes.
2. ``Store.push_project_changes`` pushes that commit to a bare-repo remote.
3. ``server._pm_store_payload`` returns the payload the dashboard reads, with
   no ``open_prs`` / ``prs`` key anywhere in it.
4. A read-only smoke test runs it against this repository.

The real repository is only ever *read* here — no test in this file commits,
pushes or writes to it.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.server import _pm_store_payload
from projectman.store import NothingToCommit, Store

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


# ─── Helpers ──────────────────────────────────────────────────────


def _git(args, cwd, check=True):
    """Run a git command in *cwd* with a deterministic identity."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        env=_GIT_ENV,
    )


def _write_store(root: Path) -> Path:
    """Create a minimal ``.project/`` store under *root*."""
    proj = root / ".project"
    proj.mkdir(parents=True, exist_ok=True)
    for d in ("stories", "tasks", "epics"):
        (proj / d).mkdir(exist_ok=True)
    config = {
        "name": "plain-repo",
        "prefix": "TST",
        "description": "subtraction check",
        "next_story_id": 1,
    }
    (proj / "config.yaml").write_text(yaml.dump(config))
    # Since US-PM-29 the five index files are derived and pm_commit rebuilds
    # them immediately before staging.  A scaffolded store has them on disk
    # and gitignored (US-PM-29-6), so this one does too — otherwise the
    # rebuild would stage five files behind every commit and "a clean store
    # is nothing to commit" could never hold.
    from projectman.indexer import write_index, write_store_gitignore

    write_index(Store(root))
    write_store_gitignore(proj)
    return proj


def _story(proj: Path, story_id: str) -> None:
    (proj / "stories" / f"{story_id}.md").write_text(
        f"# {story_id}\n\nstatus: todo\n"
    )


def _task(proj: Path, task_id: str) -> None:
    (proj / "tasks" / f"{task_id}.md").write_text(
        f"# {task_id}\n\nstatus: todo\n"
    )


def _make_repo(root: Path) -> Path:
    """A git repo on ``main`` whose ``.project/`` store is already committed."""
    root.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)
    proj = _write_store(root)
    (root / "README.md").write_text("# repo\n")
    _git(["add", "."], root)
    _git(["commit", "-m", "initial"], root)
    return proj


def _commit(root: Path, message=None):
    """``Store.commit_project_changes``, with the expected negative as a dict."""
    from projectman.store import _cache

    _cache.clear()
    try:
        result = Store(root).commit_project_changes(message=message)
    except NothingToCommit:
        return {"nothing_to_commit": True}
    result["files_committed"] = result.pop("files_changed")
    return result


def _keys_recursively(obj) -> set:
    """Every mapping key appearing anywhere inside *obj*."""
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            found |= _keys_recursively(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found |= _keys_recursively(item)
    return found


# ─── 1. commit_project_changes lands a commit with the store files ─

class TestPmCommitEndToEnd:
    """The commit path still commits ``.project/`` changes on a real repo."""

    def test_commit_lands_with_store_files_and_id_message(self, tmp_path):
        """A single changed story commits as ``pm: update <ID>``."""
        repo = tmp_path / "work"
        proj = _make_repo(repo)

        _story(proj, "US-TST-1")

        result = _commit(repo)

        assert "nothing_to_commit" not in result, result
        assert result["commit_hash"], result
        assert result["on_branch"] == "main"
        assert result["files_committed"] == [".project/stories/US-TST-1.md"]
        # Message shape pinned by Store._generate_commit_message.
        assert result["message"] == "pm: update 1 story"

        # The commit really exists and carries the store file.
        show = _git(
            ["show", "--name-only", "--pretty=format:%H%n%s", result["commit_hash"]],
            repo,
        ).stdout.splitlines()
        assert show[0] == result["commit_hash"]
        assert show[1] == "pm: update 1 story"
        assert ".project/stories/US-TST-1.md" in show

        # Nothing left uncommitted under the store.
        porcelain = _git(
            ["status", "--porcelain", "--untracked-files=all", "--", ".project"],
            repo,
        ).stdout.strip()
        assert porcelain == "", porcelain

    def test_commit_summarises_many_files(self, tmp_path):
        """More than four changed items fall back to count summaries."""
        repo = tmp_path / "work"
        proj = _make_repo(repo)

        for n in range(1, 4):
            _story(proj, f"US-TST-{n}")
        _task(proj, "US-TST-1-1")
        _task(proj, "US-TST-1-2")

        result = _commit(repo)

        assert result["commit_hash"]
        assert len(result["files_committed"]) == 5
        assert "3 stories" in result["message"]
        assert "2 tasks" in result["message"]

    def test_commit_reports_nothing_to_commit_on_clean_store(self, tmp_path):
        """A clean store is still an expected negative, not an error."""
        repo = tmp_path / "work"
        _make_repo(repo)

        assert _commit(repo) == {"nothing_to_commit": True}


# ─── 2. push_project_changes pushes to a bare remote ──────────────


class TestPmPushEndToEnd:
    """The push path still sends store commits to the configured remote."""

    @pytest.fixture
    def repo_with_bare_remote(self, tmp_path):
        """A repo on ``main`` tracking a bare remote in *tmp_path*."""
        bare = tmp_path / "origin.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], bare)

        repo = tmp_path / "work"
        proj = _make_repo(repo)
        _git(["remote", "add", "origin", str(bare)], repo)
        _git(["push", "-u", "origin", "main"], repo)
        return {"repo": repo, "proj": proj, "bare": bare}

    def test_push_sends_the_pm_commit_to_the_remote(self, repo_with_bare_remote):
        repo = repo_with_bare_remote["repo"]
        bare = repo_with_bare_remote["bare"]

        remote_before = _git(["rev-parse", "main"], bare).stdout.strip()

        _story(repo_with_bare_remote["proj"], "US-TST-9")
        commit = _commit(repo)
        local_sha = commit["commit_hash"]

        # Committing must not push (US-PRJ-5-4 behaviour is unchanged).
        assert _git(["rev-parse", "main"], bare).stdout.strip() == remote_before

        result = Store(repo).push_project_changes()

        assert result["branch"] == "main"
        assert result["remote"] == "origin"
        assert "error" not in result

        assert _git(["rev-parse", "main"], bare).stdout.strip() == local_sha

    def test_push_refuses_a_missing_remote_without_pushing(self, repo_with_bare_remote):
        """An unknown remote is refused — and nothing is pushed."""
        repo = repo_with_bare_remote["repo"]
        bare = repo_with_bare_remote["bare"]
        before = _git(["rev-parse", "main"], bare).stdout.strip()

        with pytest.raises(RuntimeError, match="emote"):
            Store(repo).push_project_changes(remote="nowhere")

        assert _git(["rev-parse", "main"], bare).stdout.strip() == before


# ─── 3. _pm_store_payload returns the dashboard payload ───────────


class TestGitStatusPayload:
    """``_pm_store_payload`` keeps the shape the dashboard renders."""

    #: Keys read off the top level of the ``pm_git_status`` answer.
    DASHBOARD_KEYS = {"summary", "pm_store"}

    def test_payload_keys(self, tmp_path):
        repo = tmp_path / "work"
        proj = _make_repo(repo)
        _story(proj, "US-TST-2")  # leave the tree dirty

        data = _pm_store_payload(repo)

        assert self.DASHBOARD_KEYS <= set(data)

        store = data["pm_store"]
        for key in (
            "path", "worktree", "branch", "detached", "head", "upstream",
            "ahead", "behind", "dirty", "dirty_count", "description",
        ):
            assert key in store, f"pm_store lost the '{key}' key"
        assert store["worktree"] is False
        assert store["branch"] == "main"
        assert store["dirty"] is True
        assert store["dirty_count"] >= 1
        assert store["description"] in data["summary"]

    def test_no_pr_keys_anywhere_in_the_payload(self, tmp_path):
        repo = tmp_path / "work"
        _make_repo(repo)

        keys = _keys_recursively(_pm_store_payload(repo))

        assert "open_prs" not in keys
        assert "prs" not in keys
        assert not any("pull_request" in k for k in keys)

    def test_no_project_registry_keys_survive(self, tmp_path):
        """Hub mode is gone: nothing enumerates sibling projects any more."""
        repo = tmp_path / "work"
        _make_repo(repo)

        keys = _keys_recursively(_pm_store_payload(repo))

        assert "projects" not in keys
        assert "issues" not in keys


# ─── 4. Read-only smoke test against this repository ──────────────


class TestGitStatusOnThisRepo:
    """``_pm_store_payload`` is safe to run against the real checkout."""

    def test_reports_this_repo_without_raising(self):
        assert (REPO_ROOT / ".project").is_dir(), REPO_ROOT
        assert (REPO_ROOT / ".git").exists(), REPO_ROOT

        data = _pm_store_payload(REPO_ROOT)  # must not raise

        assert TestGitStatusPayload.DASHBOARD_KEYS <= set(data)
        assert "open_prs" not in _keys_recursively(data)

        store = data["pm_store"]
        assert isinstance(store["dirty"], bool)
        assert store["description"] in data["summary"]
