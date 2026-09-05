"""The kept git operations still behave as before the changeset/PR subtraction.

Verifies the acceptance criterion for story US-PM-27 (task US-PM-27-3):

    > pm_commit and pm_push and pm_git_status behave as before on this repo
    > and their tests pass

Changesets and the hub pull-request workflow were removed from
``src/projectman`` (US-PM-27-6/7/8).  ``pm_commit``, ``pm_push`` and
``git_status_all`` were meant to survive untouched, so this file drives them
end to end against throwaway git repos under ``tmp_path``:

1. ``pm_commit`` lands a real commit carrying the ``.project/`` store files,
   with the auto-generated message shapes ``tests/test_hub.py`` pins.
2. ``pm_push`` pushes that commit to a bare-repo remote.
3. ``git_status_all`` returns the non-hub payload the dashboard reads, with
   no ``open_prs`` / ``prs`` key anywhere in it.
4. A read-only smoke test runs ``git_status_all`` against this repository.

The real repository is only ever *read* here — no test in this file commits,
pushes or writes to it.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from projectman.hub.registry import (
    format_git_status,
    git_status_all,
    pm_commit,
    pm_push,
)

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


def _write_store(root: Path, *, hub: bool) -> Path:
    """Create a minimal ``.project/`` store under *root*."""
    proj = root / ".project"
    proj.mkdir(parents=True, exist_ok=True)
    for d in ("stories", "tasks", "epics", "projects", "dashboards"):
        (proj / d).mkdir(exist_ok=True)
    config = {
        "name": "hub-repo" if hub else "plain-repo",
        "prefix": "TST",
        "description": "subtraction check",
        "hub": hub,
        "next_story_id": 1,
        "projects": [],
    }
    (proj / "config.yaml").write_text(yaml.dump(config))
    return proj


def _story(proj: Path, story_id: str) -> None:
    (proj / "stories" / f"{story_id}.md").write_text(
        f"# {story_id}\n\nstatus: todo\n"
    )


def _task(proj: Path, task_id: str) -> None:
    (proj / "tasks" / f"{task_id}.md").write_text(
        f"# {task_id}\n\nstatus: todo\n"
    )


def _make_repo(root: Path, *, hub: bool) -> Path:
    """A git repo on ``main`` whose ``.project/`` store is already committed."""
    root.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)
    proj = _write_store(root, hub=hub)
    (root / "README.md").write_text("# repo\n")
    _git(["add", "."], root)
    _git(["commit", "-m", "initial"], root)
    return proj


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


# ─── 1. pm_commit lands a commit with the store files ─────────────


class TestPmCommitEndToEnd:
    """pm_commit still commits ``.project/`` changes on a real repo."""

    def test_commit_lands_with_store_files_and_id_message(self, tmp_path):
        """A single changed story commits as ``pm: update <ID>``."""
        repo = tmp_path / "work"
        proj = _make_repo(repo, hub=False)

        _story(proj, "US-TST-1")

        result = pm_commit(scope="all", root=repo)

        assert "nothing_to_commit" not in result, result
        assert result["commit_hash"], result
        assert result["on_branch"] == "main"
        assert result["files_committed"] == [".project/stories/US-TST-1.md"]
        # Message shape pinned by tests/test_hub.py::
        # test_generate_hub_commit_message_few_ids
        assert result["message"] == "pm: update US-TST-1"

        # The commit really exists and carries the store file.
        show = _git(
            ["show", "--name-only", "--pretty=format:%H%n%s", result["commit_hash"]],
            repo,
        ).stdout.splitlines()
        assert show[0] == result["commit_hash"]
        assert show[1] == "pm: update US-TST-1"
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
        proj = _make_repo(repo, hub=False)

        for n in range(1, 4):
            _story(proj, f"US-TST-{n}")
        _task(proj, "US-TST-1-1")
        _task(proj, "US-TST-1-2")

        result = pm_commit(scope="all", root=repo)

        assert result["commit_hash"]
        assert len(result["files_committed"]) == 5
        # Shape pinned by test_generate_hub_commit_message_many_ids.
        assert "3 stories" in result["message"]
        assert "2 tasks" in result["message"]

    def test_commit_reports_nothing_to_commit_on_clean_store(self, tmp_path):
        """A clean store is still an expected negative, not an error."""
        repo = tmp_path / "work"
        _make_repo(repo, hub=False)

        assert pm_commit(scope="all", root=repo) == {"nothing_to_commit": True}


# ─── 2. pm_push pushes to a bare remote ───────────────────────────


class TestPmPushEndToEnd:
    """pm_push still pushes hub commits to the configured remote."""

    @pytest.fixture
    def hub_with_bare_remote(self, tmp_path):
        """A hub repo on ``main`` tracking a bare remote in *tmp_path*."""
        bare = tmp_path / "origin.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], bare)

        repo = tmp_path / "hub"
        proj = _make_repo(repo, hub=True)
        _git(["remote", "add", "origin", str(bare)], repo)
        _git(["push", "-u", "origin", "main"], repo)
        return {"repo": repo, "proj": proj, "bare": bare}

    def test_push_sends_the_pm_commit_to_the_remote(self, hub_with_bare_remote):
        repo = hub_with_bare_remote["repo"]
        bare = hub_with_bare_remote["bare"]

        remote_before = _git(["rev-parse", "main"], bare).stdout.strip()

        _story(hub_with_bare_remote["proj"], "US-TST-9")
        commit = pm_commit(scope="all", root=repo)
        local_sha = commit["commit_hash"]

        # Committing must not push (US-PRJ-5-4 behaviour is unchanged).
        assert _git(["rev-parse", "main"], bare).stdout.strip() == remote_before

        result = pm_push(scope="hub", root=repo)

        assert result["pushed"] is True, result
        assert result["scope"] == "hub"
        assert result["status"] == "pushed"
        assert result["attempts"] == 1
        assert "error" not in result

        assert _git(["rev-parse", "main"], bare).stdout.strip() == local_sha

    def test_push_rejects_unknown_scope_without_pushing(self, hub_with_bare_remote):
        """Scope validation still returns an error dict rather than raising."""
        result = pm_push(scope="bogus", root=hub_with_bare_remote["repo"])

        assert result["pushed"] is False
        assert "invalid scope" in result["error"]


# ─── 3. git_status_all returns the non-hub payload ────────────────


class TestGitStatusAllPayload:
    """git_status_all keeps the shape the dashboard renders."""

    # Keys read by tests/test_git_status_dashboard.py off the top level.
    DASHBOARD_KEYS = {"projects", "total", "issues", "ok", "summary", "pm_store"}

    def test_non_hub_payload_keys(self, tmp_path):
        repo = tmp_path / "work"
        proj = _make_repo(repo, hub=False)
        _story(proj, "US-TST-2")  # leave the tree dirty

        data = git_status_all(root=repo)

        assert self.DASHBOARD_KEYS <= set(data)
        assert data["projects"] == []
        assert data["total"] == 0
        assert data["issues"] == 0
        assert data["ok"] is False
        assert "Not a hub project" in data["summary"]

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

        # Rendering the payload must still work.
        rendered = format_git_status(data)
        assert isinstance(rendered, str) and rendered.strip()

    def test_no_pr_keys_anywhere_in_the_payload(self, tmp_path):
        repo = tmp_path / "work"
        _make_repo(repo, hub=False)

        keys = _keys_recursively(git_status_all(root=repo))

        assert "open_prs" not in keys
        assert "prs" not in keys
        assert not any("pull_request" in k for k in keys)

    def test_hub_payload_still_lists_projects(self, tmp_path):
        """An empty hub reports the registered-project payload, not a PR one."""
        repo = tmp_path / "hub"
        _make_repo(repo, hub=True)

        data = git_status_all(root=repo)

        assert self.DASHBOARD_KEYS <= set(data)
        assert data["ok"] is True
        assert data["total"] == 0
        assert "No projects registered" in data["summary"]
        assert "open_prs" not in _keys_recursively(data)


# ─── 4. Read-only smoke test against this repository ──────────────


class TestGitStatusAllOnThisRepo:
    """git_status_all is safe to run against the real ProjectMan checkout."""

    def test_reports_this_repo_without_raising(self):
        assert (REPO_ROOT / ".project").is_dir(), REPO_ROOT
        assert (REPO_ROOT / ".git").exists(), REPO_ROOT

        # What git itself says about the store, before asking ProjectMan.
        porcelain = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", ".project"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        ).stdout.strip()

        data = git_status_all(root=REPO_ROOT)  # must not raise

        assert TestGitStatusAllPayload.DASHBOARD_KEYS <= set(data)
        assert "open_prs" not in _keys_recursively(data)
        assert isinstance(format_git_status(data), str)

        store = data["pm_store"]
        assert store["dirty"] is bool(porcelain), (
            f"pm_store dirty={store['dirty']} but git reports "
            f"{len(porcelain.splitlines())} changed paths"
        )
        # This working tree is dirty by design while US-PM-27 is in flight.
        assert store["dirty"] is True
        assert store["dirty_count"] > 0
        assert store["description"] in data["summary"]
