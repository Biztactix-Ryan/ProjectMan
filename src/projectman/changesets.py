"""CRUD convenience functions for cross-repo changesets.

These wrap :class:`Store` methods and add ``update_changeset_status()``
and ``changeset_check_status()`` which are not part of the generic
Store interface.
"""

import json
import shlex
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

import frontmatter

from .models import ChangesetFrontmatter, ChangesetStatus
from .store import Store


def create_changeset(
    store: Store,
    title: str,
    projects: list[str],
    description: str = "",
) -> ChangesetFrontmatter:
    """Create a changeset grouping changes across multiple projects."""
    return store.create_changeset(title, projects, description)


def get_changeset(
    store: Store, changeset_id: str
) -> tuple[ChangesetFrontmatter, str]:
    """Read a changeset, returning (frontmatter, body)."""
    return store.get_changeset(changeset_id)


def list_changesets(
    store: Store, status: Optional[str] = None
) -> list[ChangesetFrontmatter]:
    """List all changesets, optionally filtered by status."""
    return store.list_changesets(status)


def add_project_to_changeset(
    store: Store,
    changeset_id: str,
    project: str,
    ref: str = "",
) -> ChangesetFrontmatter:
    """Add a project entry to an existing changeset."""
    return store.add_changeset_entry(changeset_id, project, ref=ref)


def update_changeset_status(
    store: Store,
    changeset_id: str,
    status: str,
) -> ChangesetFrontmatter:
    """Update the top-level status of a changeset.

    Args:
        store: The Store instance.
        changeset_id: Changeset ID (e.g. ``CS-PRJ-1``).
        status: New status — one of ``open``, ``partial``, ``merged``, ``closed``.

    Returns:
        The updated :class:`ChangesetFrontmatter`.
    """
    from datetime import date

    meta, body = store.get_changeset(changeset_id)
    meta.status = ChangesetStatus(status)
    meta.updated = date.today()

    post = frontmatter.Post(
        content=body,
        **meta.model_dump(mode="json"),
    )
    store._changeset_path(changeset_id).write_text(frontmatter.dumps(post))
    return meta


def _reject_nul(field: str, value: str) -> None:
    """Refuse a NUL byte rather than render a command that cannot run.

    ``execve`` arguments are NUL-terminated, so no argv element can carry
    one: :func:`subprocess.run` raises ``ValueError: embedded null byte``
    and a shell truncates the argument at the NUL.  ``shlex.quote`` will
    happily wrap one, which would hand the caller a *display* string that
    silently differs from what would execute.  Both forms are therefore
    rejected up front, naming the offending field.
    """
    if "\x00" in value:
        raise ValueError(
            f"{field} contains a NUL byte (0x00), which cannot be carried in a "
            "command argument; remove it from the changeset before generating "
            "PR commands"
        )


def changeset_create_prs(
    store: Store,
    changeset_id: str,
) -> dict:
    """Generate PR creation commands for all projects in a changeset with cross-references.

    Returns a dict with ``changeset``, ``title``, and ``pr_commands``.
    Each command object includes the project name, ref, an ``argv`` list
    (for callers that execute the command without a shell) and a
    shell-safe ``command`` display string built with :func:`shlex.join`.
    Entries without a ref are skipped with a status message.

    Titles, bodies and refs are user/agent-supplied, so every value is
    quoted: a ``"``, backtick, ``$(``, ``;`` or newline in any of them
    cannot break out of its argument.

    Raises:
        ValueError: If the changeset has no project entries, or if the id,
            title, description, a project name or a ref contains a NUL byte
            (no argv element can carry one — see :func:`_reject_nul`).
        FileNotFoundError: If the changeset does not exist.
    """
    meta, body = store.get_changeset(changeset_id)

    if not meta.entries:
        raise ValueError("changeset has no project entries")

    _reject_nul(f"changeset {meta.id} id", meta.id)
    _reject_nul(f"changeset {meta.id} title", meta.title)
    _reject_nul(f"changeset {meta.id} description", body or "")
    for entry in meta.entries:
        _reject_nul(f"changeset {meta.id} project name", entry.project)
        _reject_nul(f"changeset {meta.id} ref for {entry.project!r}", entry.ref or "")

    pr_commands: list[dict] = []
    cross_refs = [f"- {e.project} (ref: {e.ref or 'TBD'})" for e in meta.entries]
    cross_ref_block = "\n".join(cross_refs)

    for entry in meta.entries:
        if not entry.ref:
            pr_commands.append({
                "project": entry.project,
                "status": "skipped — no ref/branch set",
            })
            continue

        pr_body = (
            f"## Part of changeset: {meta.title} ({meta.id})\n\n"
            f"### Cross-references\n{cross_ref_block}\n\n"
            f"{body or ''}"
        )
        argv = [
            "gh", "pr", "create",
            "--title", f"{meta.title}: {entry.project}",
            "--body", pr_body,
            "--head", entry.ref,
        ]
        cmd = f"cd {shlex.quote(entry.project)} && {shlex.join(argv)}"
        pr_commands.append({
            "project": entry.project,
            "ref": entry.ref,
            "argv": argv,
            "command": cmd,
        })

    return {
        "changeset": meta.id,
        "title": meta.title,
        "pr_commands": pr_commands,
    }


def changeset_check_status(
    store: Store,
    changeset_id: str,
    root: Optional[Path] = None,
) -> dict:
    """Check PR merge status for all projects in a changeset via ``gh`` CLI.

    For each entry with a ``pr_number``, runs
    ``gh pr view {number} --json state,mergedAt`` inside the subproject
    directory at ``root/projects/{project}/``.

    Updates per-entry status and the changeset's top-level status:
    - All PRs merged → ``"merged"``
    - Some merged, some open → ``"partial"``
    - Any closed (not merged) → flagged for review

    Args:
        store: The Store instance.
        changeset_id: Changeset ID (e.g. ``CS-PRJ-1``).
        root: Hub root directory.  Falls back to ``store.root``.

    Returns:
        A dict with ``changeset``, ``status``, ``entries`` (per-project
        detail), and ``needs_review`` (bool).
    """
    root = root or store.root
    meta, body = store.get_changeset(changeset_id)

    results: list[dict] = []
    for entry in meta.entries:
        if entry.pr_number is None:
            results.append({
                "project": entry.project,
                "status": "no-pr",
                "message": "No PR number set",
            })
            continue

        project_dir = root / "projects" / entry.project
        try:
            output = subprocess.run(
                [
                    "gh", "pr", "view", str(entry.pr_number),
                    "--json", "state,mergedAt",
                ],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                check=True,
            )
            pr_data = json.loads(output.stdout)
            state = pr_data.get("state", "UNKNOWN")
            merged_at = pr_data.get("mergedAt")

            if state == "MERGED":
                entry.status = "merged"
            elif state == "CLOSED":
                entry.status = "closed"
            elif state == "OPEN":
                entry.status = "open"

            results.append({
                "project": entry.project,
                "pr_number": entry.pr_number,
                "state": state,
                "merged_at": merged_at,
                "status": entry.status,
            })
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            err_msg = e.stderr.strip() if hasattr(e, "stderr") and e.stderr else str(e)
            results.append({
                "project": entry.project,
                "pr_number": entry.pr_number,
                "status": "error",
                "message": err_msg,
            })

    # Determine overall status
    closed_not_merged = [e for e in meta.entries if e.status == "closed"]
    merged = [e for e in meta.entries if e.status == "merged"]

    if closed_not_merged:
        new_status = "closed"
    elif merged and len(merged) == len(meta.entries):
        new_status = "merged"
    elif merged:
        new_status = "partial"
    else:
        new_status = "open"

    meta.status = ChangesetStatus(new_status)
    meta.updated = date.today()

    post = frontmatter.Post(content=body, **meta.model_dump(mode="json"))
    store._changeset_path(changeset_id).write_text(frontmatter.dumps(post))

    return {
        "changeset": meta.id,
        "status": new_status,
        "entries": results,
        "needs_review": bool(closed_not_merged),
    }
